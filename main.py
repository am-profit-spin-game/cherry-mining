
import os
import json
import hmac
import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_defunct

load_dotenv()

app = FastAPI(title="Cherry Mining API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_TELEGRAM_IDS = {
    x.strip() for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip()
}

MIN_WITHDRAW = 10000
CHERRY_PER_USD = 10000
DAILY_REWARD = 100
MINING_HOURS = 24
MINING_REWARD = int(os.getenv("MINING_REWARD", "500"))
REFERRAL_REWARD = int(os.getenv("REFERRAL_REWARD", "100"))
TASK_REWARD = int(os.getenv("TASK_REWARD", "50"))
MONETAG_SECRET = os.getenv("MONETAG_SECRET", "")

app.state.ready = False


# ---------------- DATABASE ----------------

def db():
    if not DATABASE_URL:
        raise HTTPException(500, "DATABASE_URL is not configured")

    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require"
    )


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id BIGINT PRIMARY KEY,
        first_name TEXT DEFAULT '',
        username TEXT DEFAULT '',
        balance BIGINT NOT NULL DEFAULT 0,
        wallet_address TEXT DEFAULT '',
        wallet_verified BOOLEAN NOT NULL DEFAULT FALSE,
        referred_by BIGINT,
        referral_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_daily TIMESTAMPTZ,
        mining_started TIMESTAMPTZ,
        mining_ends TIMESTAMPTZ
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ad_sessions (
        id TEXT PRIMARY KEY,
        ymid TEXT UNIQUE NOT NULL,
        telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
        task_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        rewarded_at TIMESTAMPTZ
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ad_events (
        id BIGSERIAL PRIMARY KEY,
        ymid TEXT NOT NULL,
        event_type TEXT NOT NULL,
        reward_event_type TEXT,
        estimated_price NUMERIC(14, 8) DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(ymid, event_type)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_claims (
        id BIGSERIAL PRIMARY KEY,
        telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
        task_id INTEGER NOT NULL,
        claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(telegram_id, task_id, claimed_at)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id BIGSERIAL PRIMARY KEY,
        telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
        amount BIGINT NOT NULL,
        wallet_address TEXT NOT NULL,
        network TEXT NOT NULL DEFAULT 'BEP20',
        status TEXT NOT NULL DEFAULT 'pending',
        tx_hash TEXT DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        processed_at TIMESTAMPTZ
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS wallet_challenges (
        telegram_id BIGINT PRIMARY KEY REFERENCES users(telegram_id),
        address TEXT NOT NULL,
        message TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
    )
    """)

    conn.commit()
    cur.close()
    conn.close()


@app.on_event("startup")
def startup():
    init_db()
    app.state.ready = True


# ---------------- TELEGRAM AUTH ----------------

def verify_telegram_init_data(init_data: str):
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN is not configured")

    if not init_data:
        raise HTTPException(401, "Open this app inside Telegram")

    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", None)

    if not received_hash:
        raise HTTPException(401, "Invalid Telegram data")

    auth_date = values.get("auth_date")
    if not auth_date:
        raise HTTPException(401, "Missing authentication date")

    try:
        if datetime.now(timezone.utc).timestamp() - int(auth_date) > 86400:
            raise HTTPException(401, "Telegram session expired")
    except ValueError:
        raise HTTPException(401, "Invalid authentication date")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(401, "Telegram authentication failed")

    try:
        user = json.loads(values["user"])
        return user
    except Exception:
        raise HTTPException(401, "Invalid Telegram user data")


def get_user(init_data: str):
    telegram_user = verify_telegram_init_data(init_data)

    telegram_id = int(telegram_user["id"])
    first_name = telegram_user.get("first_name", "")
    username = telegram_user.get("username", "")

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (telegram_id, first_name, username)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_id)
        DO UPDATE SET
            first_name = EXCLUDED.first_name,
            username = EXCLUDED.username
    """, (telegram_id, first_name, username))

    cur.execute(
        "SELECT * FROM users WHERE telegram_id = %s",
        (telegram_id,)
    )
    user = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()

    return user


def current_user(x_telegram_init_data: str):
    return get_user(x_telegram_init_data)


def require_admin(user_id):
    if str(user_id) not in ADMIN_TELEGRAM_IDS:
        raise HTTPException(403, "Admin access required")


# ---------------- MODELS ----------------

class WalletBody(BaseModel):
    address: str


class WithdrawBody(BaseModel):
    amount: int = Field(gt=0)
    wallet_address: str
    network: str = "BEP20"


class WalletConfirmBody(BaseModel):
    address: str
    message: str
    signature: str


class TaskCompleteBody(BaseModel):
    session_id: str


# ---------------- HELPERS ----------------

def user_data(user):
    now = datetime.now(timezone.utc)

    mining_ready = bool(
        user["mining_ends"] and user["mining_ends"] <= now
    )

    daily_next = (
        user["last_daily"] + timedelta(hours=24)
        if user["last_daily"] else None
    )

    return {
        "telegram_id": user["telegram_id"],
        "first_name": user["first_name"],
        "username": user["username"],
        "balance": user["balance"],
        "usd_balance": round(user["balance"] / CHERRY_PER_USD, 4),
        "wallet_address": user["wallet_address"],
        "wallet_verified": user["wallet_verified"],
        "referral_count": user["referral_count"],
        "mining_started": user["mining_started"].isoformat()
            if user["mining_started"] else None,
        "mining_end_at": user["mining_ends"].isoformat()
            if user["mining_ends"] else None,
        "mining_ready": mining_ready,
        "mining_reward": MINING_REWARD,
        "daily_next_at": daily_next.isoformat() if daily_next else None,
        "daily_reward": DAILY_REWARD,
        "referral_link": f"https://t.me/CherryMiningBot?start={user['telegram_id']}"
    }


def get_task_status(conn, telegram_id):
    cur = conn.cursor()
    cur.execute("""
        SELECT task_id, MAX(claimed_at) AS last_claim
        FROM task_claims
        WHERE telegram_id = %s
        GROUP BY task_id
    """, (telegram_id,))
    rows = cur.fetchall()
    cur.close()

    result = {}
    for row in rows:
        result[row["task_id"]] = row["last_claim"]

    return result


# ---------------- BASIC ----------------

@app.get("/")
def home():
    return {"status": "online", "app": "Cherry Mining"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/me")
def me(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)
    return user_data(user)


# ---------------- REFERRAL ----------------

@app.post("/api/referral/claim")
def referral_claim(
    x_telegram_init_data: str = Header(default=""),
    start: str = ""
):
    user = current_user(x_telegram_init_data)
    new_user_id = user["telegram_id"]

    try:
        referrer_id = int(start)
    except ValueError:
        raise HTTPException(400, "Invalid referral ID")

    if referrer_id == new_user_id:
        raise HTTPException(400, "Self-referral is not allowed")

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT referred_by FROM users WHERE telegram_id = %s FOR UPDATE",
        (new_user_id,)
    )
    current = cur.fetchone()

    if current["referred_by"] is not None:
        conn.rollback()
        cur.close()
        conn.close()
        return {"success": False, "message": "Referral already used"}

    cur.execute(
        "SELECT telegram_id FROM users WHERE telegram_id = %s",
        (referrer_id,)
    )
    referrer = cur.fetchone()

    if not referrer:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(404, "Referrer not found")

    cur.execute("""
        UPDATE users SET referred_by = %s
        WHERE telegram_id = %s
    """, (referrer_id, new_user_id))

    cur.execute("""
        UPDATE users
        SET balance = balance + %s,
            referral_count = referral_count + 1
        WHERE telegram_id = %s
    """, (REFERRAL_REWARD, referrer_id))

    conn.commit()
    cur.close()
    conn.close()

    return {"success": True}


# ---------------- MINING ----------------

@app.post("/api/mining/start")
def mining_start(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)
    now = datetime.now(timezone.utc)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT mining_ends FROM users
        WHERE telegram_id = %s FOR UPDATE
    """, (user["telegram_id"],))

    row = cur.fetchone()

    if row["mining_ends"] and row["mining_ends"] > now:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Mining is already running")

    end_time = now + timedelta(hours=MINING_HOURS)

    cur.execute("""
        UPDATE users
        SET mining_started = %s, mining_ends = %s
        WHERE telegram_id = %s
    """, (now, end_time, user["telegram_id"]))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "mining_end_at": end_time.isoformat()
    }


@app.post("/api/mining/claim")
def mining_claim(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)
    now = datetime.now(timezone.utc)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT mining_ends FROM users
        WHERE telegram_id = %s FOR UPDATE
    """, (user["telegram_id"],))

    row = cur.fetchone()

    if not row["mining_ends"] or row["mining_ends"] > now:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Mining is not completed yet")

    cur.execute("""
        UPDATE users
        SET balance = balance + %s,
            mining_started = NULL,
            mining_ends = NULL
        WHERE telegram_id = %s
    """, (MINING_REWARD, user["telegram_id"]))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "reward": MINING_REWARD
    }


# ---------------- DAILY BONUS ----------------

@app.post("/api/daily/claim")
def daily_claim(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)
    now = datetime.now(timezone.utc)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT last_daily FROM users
        WHERE telegram_id = %s FOR UPDATE
    """, (user["telegram_id"],))

    row = cur.fetchone()

    if row["last_daily"] and row["last_daily"] + timedelta(hours=24) > now:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Daily bonus is not ready")

    cur.execute("""
        UPDATE users
        SET balance = balance + %s, last_daily = %s
        WHERE telegram_id = %s
    """, (DAILY_REWARD, now, user["telegram_id"]))

    conn.commit()
    cur.close()
    conn.close()

    return {"success": True, "reward": DAILY_REWARD}


# ---------------- TASKS ----------------

@app.get("/api/tasks")
def tasks(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)

    conn = db()
    claimed = get_task_status(conn, user["telegram_id"])
    conn.close()

    now = datetime.now(timezone.utc)
    result = []

    for task_id in range(1, 11):
        last_claim = claimed.get(task_id)
        completed = bool(
            last_claim and last_claim + timedelta(hours=24) > now
        )

        result.append({
            "id": task_id,
            "title": f"Daily Ad Task {task_id}",
            "description": "Watch a rewarded ad to earn Cherry.",
            "reward": TASK_REWARD,
            "completed": completed,
            "next_available_at": (
                (last_claim + timedelta(hours=24)).isoformat()
                if completed else None
            )
        })

    return {"tasks": result}


@app.post("/api/ads/session")
def create_ad_session(
    x_telegram_init_data: str = Header(default=""),
    task_id: int = 1
):
    user = current_user(x_telegram_init_data)

    if task_id < 1 or task_id > 10:
        raise HTTPException(400, "Invalid task")

    session_id = secrets.token_urlsafe(18)
    ymid = "cm_" + secrets.token_hex(16)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO ad_sessions (id, ymid, telegram_id, task_id)
        VALUES (%s, %s, %s, %s)
    """, (session_id, ymid, user["telegram_id"], task_id))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "session_id": session_id,
        "ymid": ymid,
        "task_id": task_id
    }


@app.get("/api/ads/session/{session_id}")
def get_ad_session(
    session_id: str,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT status FROM ad_sessions
        WHERE id = %s AND telegram_id = %s
    """, (session_id, user["telegram_id"]))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(404, "Ad session not found")

    return {"status": row["status"]}


@app.post("/api/tasks/{task_id}/complete")
def complete_task(
    task_id: int,
    body: TaskCompleteBody,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)
    now = datetime.now(timezone.utc)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM ad_sessions
        WHERE id = %s AND telegram_id = %s AND task_id = %s
        FOR UPDATE
    """, (body.session_id, user["telegram_id"], task_id))

    session = cur.fetchone()

    if not session or session["status"] != "valued":
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Verified ad reward not found")

    cur.execute("""
        SELECT claimed_at FROM task_claims
        WHERE telegram_id = %s AND task_id = %s
        ORDER BY claimed_at DESC LIMIT 1
    """, (user["telegram_id"], task_id))

    previous = cur.fetchone()

    if previous and previous["claimed_at"] + timedelta(hours=24) > now:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Task already completed today")

    cur.execute("""
        INSERT INTO task_claims (telegram_id, task_id)
        VALUES (%s, %s)
    """, (user["telegram_id"], task_id))

    cur.execute("""
        UPDATE users SET balance = balance + %s
        WHERE telegram_id = %s
    """, (TASK_REWARD, user["telegram_id"]))

    cur.execute("""
        UPDATE ad_sessions SET status = 'claimed'
        WHERE id = %s
    """, (body.session_id,))

    conn.commit()
    cur.close()
    conn.close()

    return {"success": True, "reward": TASK_REWARD}


# ---------------- MONETAG POSTBACK ----------------

@app.get("/postback/monetag")
def monetag_postback(
    secret: str = "",
    ymid: str = "",
    event_type: str = "",
    reward_event_type: str = "",
    estimated_price: float = 0,
    telegram_id: str = "",
    zone_id: str = ""
):
    if not MONETAG_SECRET or not hmac.compare_digest(secret, MONETAG_SECRET):
        raise HTTPException(403, "Invalid postback secret")

    if not ymid or event_type not in ("impression", "click"):
        raise HTTPException(400, "Invalid postback")

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM ad_sessions WHERE ymid = %s FOR UPDATE
    """, (ymid,))
    session = cur.fetchone()

    if not session:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(404, "Unknown ad session")

    cur.execute("""
        INSERT INTO ad_events
        (ymid, event_type, reward_event_type, estimated_price)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (ymid, event_type) DO NOTHING
    """, (ymid, event_type, reward_event_type, estimated_price))

    # Reward only once, on Monetag's valued impression.
    if event_type == "impression" and reward_event_type == "valued":
        cur.execute("""
            UPDATE ad_sessions
            SET status = 'valued'
            WHERE ymid = %s AND status = 'pending'
        """, (ymid,))

    elif event_type == "impression" and reward_event_type == "non_valued":
        cur.execute("""
            UPDATE ad_sessions
            SET status = 'rejected'
            WHERE ymid = %s AND status = 'pending'
        """, (ymid,))

    conn.commit()
    cur.close()
    conn.close()

    return {"received": True}


# ---------------- WALLET ----------------

def valid_bsc_address(address):
    return (
        isinstance(address, str)
        and len(address) == 42
        and address.startswith("0x")
        and all(c in string.hexdigits for c in address[2:])
    )


@app.post("/api/wallet")
def save_wallet(
    body: WalletBody,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    if not valid_bsc_address(body.address):
        raise HTTPException(400, "Invalid BNB Smart Chain wallet address")

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET wallet_address = %s, wallet_verified = FALSE
        WHERE telegram_id = %s
    """, (body.address, user["telegram_id"]))

    conn.commit()
    cur.close()
    conn.close()

    return {"success": True}


@app.post("/api/wallet/verification/challenge")
def wallet_challenge(
    body: WalletBody,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    if not valid_bsc_address(body.address):
        raise HTTPException(400, "Invalid wallet address")

    nonce = secrets.token_urlsafe(24)
    message = (
        "Cherry Mining Wallet Verification\n"
        f"Telegram ID: {user['telegram_id']}\n"
        f"Wallet: {body.address}\n"
        f"Nonce: {nonce}\n"
        "This signature does not authorize a transaction."
    )

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO wallet_challenges
        (telegram_id, address, message, expires_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (telegram_id)
        DO UPDATE SET
            address = EXCLUDED.address,
            message = EXCLUDED.message,
            expires_at = EXCLUDED.expires_at
    """, (
        user["telegram_id"],
        body.address,
        message,
        datetime.now(timezone.utc) + timedelta(minutes=5)
    ))

    conn.commit()
    cur.close()
    conn.close()

    return {"message": message}


@app.post("/api/wallet/verification/confirm")
def wallet_confirm(
    body: WalletConfirmBody,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM wallet_challenges
        WHERE telegram_id = %s FOR UPDATE
    """, (user["telegram_id"],))

    challenge = cur.fetchone()

    if (
        not challenge
        or challenge["address"].lower() != body.address.lower()
        or challenge["message"] != body.message
        or challenge["expires_at"] < datetime.now(timezone.utc)
    ):
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Wallet verification challenge expired or invalid")

    try:
        signed_message = encode_defunct(text=body.message)
        recovered = Account.recover_message(
            signed_message,
            signature=body.signature
        )
    except Exception:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Invalid wallet signature")

    if recovered.lower() != body.address.lower():
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Signature does not match wallet")

    cur.execute("""
        UPDATE users
        SET wallet_address = %s, wallet_verified = TRUE
        WHERE telegram_id = %s
    """, (body.address, user["telegram_id"]))

    cur.execute("""
        DELETE FROM wallet_challenges WHERE telegram_id = %s
    """, (user["telegram_id"],))

    conn.commit()
    cur.close()
    conn.close()

    return {"success": True, "verified": True}


# ---------------- WITHDRAWALS ----------------

@app.post("/api/withdraw")
def create_withdrawal(
    body: WithdrawBody,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    if body.network != "BEP20":
        raise HTTPException(400, "Only BNB Smart Chain BEP20 is supported")

    if not valid_bsc_address(body.wallet_address):
        raise HTTPException(400, "Invalid wallet address")

    if body.amount < MIN_WITHDRAW:
        raise HTTPException(400, "Minimum withdrawal is 10,000 Cherry")

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM users WHERE telegram_id = %s FOR UPDATE
    """, (user["telegram_id"],))
    account = cur.fetchone()

    if not account["wallet_address"]:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Save your wallet first")

    if account["wallet_address"].lower() != body.wallet_address.lower():
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Withdrawal wallet does not match saved wallet")

    cur.execute("""
        SELECT COUNT(*) AS total FROM withdrawals
        WHERE telegram_id = %s
    """, (user["telegram_id"],))
    previous_count = cur.fetchone()["total"]

    if previous_count > 0 and not account["wallet_verified"]:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(
            400,
            "Wallet verification is required for subsequent withdrawals"
        )

    if account["balance"] < body.amount:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Insufficient Cherry balance")

    cur.execute("""
        UPDATE users SET balance = balance - %s
        WHERE telegram_id = %s
    """, (body.amount, user["telegram_id"]))

    cur.execute("""
        INSERT INTO withdrawals
        (telegram_id, amount, wallet_address, network)
        VALUES (%s, %s, %s, 'BEP20')
        RETURNING id
    """, (
        user["telegram_id"],
        body.amount,
        body.wallet_address
    ))

    withdrawal_id = cur.fetchone()["id"]

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "withdrawal_id": withdrawal_id,
        "status": "pending"
    }


@app.get("/api/withdrawals")
def withdrawal_history(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, amount, wallet_address, network, status,
               tx_hash, created_at
        FROM withdrawals
        WHERE telegram_id = %s
        ORDER BY created_at DESC
        LIMIT 50
    """, (user["telegram_id"],))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return {"withdrawals": [
        {
            **dict(row),
            "created_at": row["created_at"].isoformat()
        } for row in rows
    ]}


# ---------------- ADMIN ----------------

@app.get("/api/admin/withdrawals")
def admin_withdrawals(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)
    require_admin(user["telegram_id"])

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM withdrawals
        WHERE status = 'pending'
        ORDER BY created_at ASC
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return {"withdrawals": [
        {**dict(row), "created_at": row["created_at"].isoformat()}
        for row in rows
    ]}


@app.post("/api/admin/withdrawals/{withdrawal_id}/approve")
def approve_withdrawal(
    withdrawal_id: int,
    request: Request,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)
    require_admin(user["telegram_id"])

    body = {}
    try:
        body = request.json()
        if hasattr(body, "__await__"):
            body = {}
    except Exception:
        body = {}

    tx_hash = ""

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE withdrawals
        SET status = 'approved',
            tx_hash = %s,
            processed_at = NOW()
        WHERE id = %s AND status = 'pending'
        RETURNING id
    """, (tx_hash, withdrawal_id))

    result = cur.fetchone()

    if not result:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(404, "Pending withdrawal not found")

    conn.commit()
    cur.close()
    conn.close()

    return {"success": True, "status": "approved"}


@app.post("/api/admin/withdrawals/{withdrawal_id}/reject")
def reject_withdrawal(
    withdrawal_id: int,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)
    require_admin(user["telegram_id"])

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT telegram_id, amount FROM withdrawals
        WHERE id = %s AND status = 'pending'
        FOR UPDATE
    """, (withdrawal_id,))

    row = cur.fetchone()

    if not row:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(404, "Pending withdrawal not found")

    cur.execute("""
        UPDATE withdrawals SET status = 'rejected',
            processed_at = NOW()
        WHERE id = %s
    """, (withdrawal_id,))

    cur.execute("""
        UPDATE users SET balance = balance + %s
        WHERE telegram_id = %s
    """, (row["amount"], row["telegram_id"]))

    conn.commit()
    cur.close()
    conn.close()

    return {"success": True, "status": "rejected"}
