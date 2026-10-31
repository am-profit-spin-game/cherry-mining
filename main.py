
import os
import json
import hmac
import hashlib
import secrets
import string
import urllib.parse
import urllib.request
import urllib.error

from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from urllib.parse import parse_qsl

import psycopg2
from psycopg2.extras import RealDictCursor

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from eth_account import Account
from eth_account.messages import encode_defunct


# ==================================================
# CONFIGURATION
# ==================================================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
MONETAG_SECRET = os.getenv("MONETAG_SECRET", "")

ADMIN_TELEGRAM_IDS = {
    x.strip()
    for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")
    if x.strip()
}

MINING_REWARD = Decimal(os.getenv("MINING_REWARD", "500"))
REFERRAL_REWARD = Decimal(os.getenv("REFERRAL_REWARD", "100"))
TASK_REWARD = Decimal(os.getenv("TASK_REWARD", "50"))

MIN_WITHDRAW = Decimal("10000")
CHERRY_PER_USD = Decimal("10000")
DAILY_REWARD = Decimal("100")

MINING_HOURS = 24

REFERRAL_TASK_LIMIT = 10
REFERRAL_DEADLINE_HOURS = 24

OFFICIAL_CHANNEL = "@CherryMiningChannel"
OFFICIAL_CHANNEL_LINK = "https://t.me/CherryMiningChannel"

app = FastAPI(title="Cherry Mining API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================================================
# DATABASE
# ==================================================

def db():
    if not DATABASE_URL:
        raise HTTPException(
            500,
            "DATABASE_URL is not configured"
        )

    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require",
        connect_timeout=15
    )


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id BIGINT PRIMARY KEY,
            first_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            balance NUMERIC(20,8) NOT NULL DEFAULT 0,
            wallet_address TEXT DEFAULT '',
            wallet_verified BOOLEAN NOT NULL DEFAULT FALSE,
            referred_by BIGINT,
            referral_count INTEGER NOT NULL DEFAULT 0,
            referral_rewarded BOOLEAN NOT NULL DEFAULT FALSE,
            referred_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_daily TIMESTAMPTZ,
            mining_started TIMESTAMPTZ,
            mining_ends TIMESTAMPTZ,
            mining_claimed_at TIMESTAMPTZ
        )
    """)

    cur.execute("""
        ALTER TABLE users
        ALTER COLUMN balance TYPE NUMERIC(20,8)
        USING balance::NUMERIC(20,8)
    """)

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS referral_rewarded
        BOOLEAN NOT NULL DEFAULT FALSE
    """)

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS referred_at TIMESTAMPTZ
    """)

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS mining_claimed_at TIMESTAMPTZ
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
            estimated_price NUMERIC(14,8) DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(ymid, event_type)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_claims (
            id BIGSERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
            task_id INTEGER NOT NULL,
            claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id BIGSERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
            amount NUMERIC(20,8) NOT NULL,
            wallet_address TEXT NOT NULL,
            network TEXT NOT NULL DEFAULT 'BEP20',
            status TEXT NOT NULL DEFAULT 'pending',
            tx_hash TEXT DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ
        )
    """)

    cur.execute("""
        ALTER TABLE withdrawals
        ALTER COLUMN amount TYPE NUMERIC(20,8)
        USING amount::NUMERIC(20,8)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_challenges (
            telegram_id BIGINT PRIMARY KEY REFERENCES users(telegram_id),
            address TEXT NOT NULL,
            message TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_withdrawals_user
        ON withdrawals(telegram_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_claims_user
        ON task_claims(telegram_id, task_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_referrer
        ON users(referred_by)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_claims_referral_window
        ON task_claims(telegram_id, claimed_at)
    """)

    conn.commit()
    cur.close()
    conn.close()


@app.on_event("startup")
def startup():
    init_db()


# ==================================================
# FRONTEND FILES
# ==================================================

@app.get("/")
def home():
    file = BASE_DIR / "index.html"

    if not file.exists():
        raise HTTPException(404, "index.html not found")

    return FileResponse(file, media_type="text/html")


@app.get("/style.css")
def serve_css():
    file = BASE_DIR / "style.css"

    if not file.exists():
        raise HTTPException(404, "style.css not found")

    return FileResponse(file, media_type="text/css")


@app.get("/app.js")
def serve_js():
    file = BASE_DIR / "app.js"

    if not file.exists():
        raise HTTPException(404, "app.js not found")

    return FileResponse(
        file,
        media_type="application/javascript"
    )


@app.get("/favicon.ico")
def favicon():
    raise HTTPException(404, "No favicon")


@app.get("/health")
def health():
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()

        return {
            "status": "ok",
            "database": "connected"
        }

    except Exception:
        raise HTTPException(
            503,
            "Database connection failed"
        )


# ==================================================
# TELEGRAM AUTHENTICATION
# ==================================================

def verify_telegram_init_data(init_data):
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN is not configured")

    if not init_data:
        raise HTTPException(
            401,
            "Open this application inside Telegram"
        )

    values = dict(
        parse_qsl(init_data, keep_blank_values=True)
    )

    received_hash = values.pop("hash", None)

    if not received_hash:
        raise HTTPException(401, "Invalid Telegram data")

    auth_date = values.get("auth_date")

    if not auth_date:
        raise HTTPException(401, "Missing authentication date")

    try:
        timestamp = int(auth_date)

        if datetime.now(timezone.utc).timestamp() - timestamp > 86400:
            raise HTTPException(401, "Telegram session expired")

    except ValueError:
        raise HTTPException(401, "Invalid authentication date")

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(values.items())
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

    if not hmac.compare_digest(
        calculated_hash,
        received_hash
    ):
        raise HTTPException(
            401,
            "Telegram authentication failed"
        )

    try:
        return json.loads(values["user"])

    except Exception:
        raise HTTPException(401, "Invalid Telegram user")


def current_user(
    x_telegram_init_data: str = Header(default="")
):
    telegram_user = verify_telegram_init_data(
        x_telegram_init_data
    )

    telegram_id = int(telegram_user["id"])

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (
            telegram_id,
            first_name,
            username
        )
        VALUES (%s, %s, %s)

        ON CONFLICT (telegram_id)
        DO UPDATE SET
            first_name = EXCLUDED.first_name,
            username = EXCLUDED.username

        RETURNING *
    """, (
        telegram_id,
        telegram_user.get("first_name", ""),
        telegram_user.get("username", "")
    ))

    user = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()

    return user


def require_admin(telegram_id):
    if str(telegram_id) not in ADMIN_TELEGRAM_IDS:
        raise HTTPException(403, "Admin access required")


# ==================================================
# OFFICIAL CHANNEL VERIFICATION
# ==================================================

def telegram_api(method, params):
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN is not configured")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    data = urllib.parse.urlencode(params).encode()

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:
            result = json.loads(response.read().decode())

    except Exception:
        raise HTTPException(
            503,
            "Telegram verification service unavailable"
        )

    if not result.get("ok"):
        raise HTTPException(
            503,
            "Unable to verify channel membership. Check bot admin permission."
        )

    return result.get("result")


def check_channel_membership(telegram_id):
    member = telegram_api(
        "getChatMember",
        {
            "chat_id": OFFICIAL_CHANNEL,
            "user_id": telegram_id
        }
    )

    status = member.get("status")

    is_member = (
        status in ("creator", "administrator", "member")
        or (
            status == "restricted"
            and member.get("is_member") is True
        )
    )

    return is_member


def require_channel(telegram_id):
    if not check_channel_membership(telegram_id):
        raise HTTPException(
            403,
            {
                "code": "CHANNEL_JOIN_REQUIRED",
                "message": "Join the official channel first",
                "channel": OFFICIAL_CHANNEL_LINK
            }
        )


@app.get("/api/channel/status")
def channel_status(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    joined = check_channel_membership(
        user["telegram_id"]
    )

    return {
        "joined": joined,
        "channel": OFFICIAL_CHANNEL_LINK
    }


@app.post("/api/channel/verify")
def channel_verify(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    joined = check_channel_membership(
        user["telegram_id"]
    )

    if not joined:
        raise HTTPException(
            403,
            {
                "code": "CHANNEL_JOIN_REQUIRED",
                "message": "You have not joined the official channel",
                "channel": OFFICIAL_CHANNEL_LINK
            }
        )

    return {
        "success": True,
        "joined": True
    }


# ==================================================
# REQUEST MODELS
# ==================================================

class WalletBody(BaseModel):
    address: str


class WithdrawBody(BaseModel):
    amount: Decimal = Field(gt=0)
    wallet_address: str
    network: str = "BEP20"


class WalletConfirmBody(BaseModel):
    address: str
    message: str
    signature: str


class TaskCompleteBody(BaseModel):
    session_id: str


class ApproveBody(BaseModel):
    tx_hash: str = ""


# ==================================================
# HELPERS
# ==================================================

def valid_bsc_address(address):
    return (
        isinstance(address, str)
        and len(address) == 42
        and address.startswith("0x")
        and all(
            char in string.hexdigits
            for char in address[2:]
        )
    )


def as_decimal(value):
    return Decimal(str(value or 0))


def usd_value(cherry):
    return (
        as_decimal(cherry) / CHERRY_PER_USD
    ).quantize(
        Decimal("0.00000001"),
        rounding=ROUND_DOWN
    )


def mining_amount(user, now=None):
    now = now or datetime.now(timezone.utc)

    started = user.get("mining_started")
    ends = user.get("mining_ends")

    if not started or not ends:
        return Decimal("0")

    if now <= started:
        return Decimal("0")

    effective_end = min(now, ends)

    claimed_at = user.get("mining_claimed_at") or started

    effective_start = max(started, claimed_at)

    if effective_end <= effective_start:
        return Decimal("0")

    total_seconds = Decimal(
        str((ends - started).total_seconds())
    )

    elapsed_seconds = Decimal(
        str((effective_end - effective_start).total_seconds())
    )

    if total_seconds <= 0:
        return Decimal("0")

    reward = (
        MINING_REWARD
        * elapsed_seconds
        / total_seconds
    )

    return reward.quantize(
        Decimal("0.00000001"),
        rounding=ROUND_DOWN
    )


def make_user_response(user):
    now = datetime.now(timezone.utc)

    pending_mining = mining_amount(user, now)

    started = user.get("mining_started")
    ends = user.get("mining_ends")

    active = bool(
        started and ends and now < ends
    )

    completed = bool(
        started and ends and now >= ends
    )

    daily_next = (
        user["last_daily"] + timedelta(hours=24)
        if user.get("last_daily")
        else None
    )

    return {
        "telegram_id": user["telegram_id"],
        "first_name": user["first_name"],
        "username": user["username"],

        "balance": float(user["balance"]),
        "usd_balance": float(usd_value(user["balance"])),

        "wallet_address": user["wallet_address"],
        "wallet_verified": user["wallet_verified"],

        "referral_count": user["referral_count"],

        "mining_started": (
            started.isoformat() if started else None
        ),

        "mining_end_at": (
            ends.isoformat() if ends else None
        ),

        "mining_active": active,
        "mining_completed": completed,

        "mining_reward": float(MINING_REWARD),

        "mining_earned": float(pending_mining),
        "mining_earned_usd": float(usd_value(pending_mining)),

        "mining_claimable": float(pending_mining),

        "mining_progress": (
            min(
                100,
                round(
                    float(
                        (now - started).total_seconds()
                        / (ends - started).total_seconds()
                        * 100
                    ),
                    2
                )
            )
            if started and ends and now > started
            else 0
        ),

        "cherry_per_usd": float(CHERRY_PER_USD),

        "daily_next_at": (
            daily_next.isoformat()
            if daily_next else None
        ),

        "daily_reward": float(DAILY_REWARD),

        "referral_link": (
            f"https://t.me/CherryMiningBot?start={user['telegram_id']}"
        )
    }


# ==================================================
# USER PROFILE
# ==================================================

@app.get("/api/me")
def me(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    return make_user_response(user)


# ==================================================
# REFERRAL SYSTEM (PATCH NEEDED)
# ==================================================

@app.post("/api/referral/claim")
def referral_claim(
    x_telegram_init_data: str = Header(default=""),
    start: str = ""
):
    user = current_user(x_telegram_init_data)

    try:
        referrer_id = int(start)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid referral ID")

    new_user_id = user["telegram_id"]

    if referrer_id == new_user_id:
        raise HTTPException(400, "Self referral not allowed")

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT referred_by
        FROM users
        WHERE telegram_id = %s
        FOR UPDATE
    """, (new_user_id,))

    account = cur.fetchone()

    if account["referred_by"] is not None:
        conn.rollback()
        cur.close()
        conn.close()

        return {
            "success": False,
            "message": "Referral already used"
        }

    cur.execute("""
        SELECT telegram_id
        FROM users
        WHERE telegram_id = %s
    """, (referrer_id,))

    referrer = cur.fetchone()

    if not referrer:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(404, "Referrer not found")

    cur.execute("""
        UPDATE users
        SET referred_by = %s,
            referred_at = NOW(),
            referral_rewarded = FALSE
        WHERE telegram_id = %s
    """, (
        referrer_id,
        new_user_id
    ))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "message": "Referral registered. Complete 10 tasks within 24 hours."
    }


def process_referral_reward(cur, telegram_id, now):
    cur.execute("""
        SELECT
            referred_by,
            referred_at,
            referral_rewarded
        FROM users
        WHERE telegram_id = %s
        FOR UPDATE
    """, (telegram_id,))

    referred = cur.fetchone()

    if not referred:
        return False

    if (
        not referred["referred_by"]
        or not referred["referred_at"]
        or referred["referral_rewarded"]
    ):
        return False

    deadline = (
        referred["referred_at"]
        + timedelta(hours=REFERRAL_DEADLINE_HOURS)
    )

    if now > deadline:
        return False

    cur.execute("""
        SELECT COUNT(DISTINCT task_id) AS total
        FROM task_claims
        WHERE telegram_id = %s
        AND claimed_at <= %s
    """, (
        telegram_id,
        deadline
    ))

    total = cur.fetchone()["total"]

    if total < REFERRAL_TASK_LIMIT:
        return False

    cur.execute("""
        UPDATE users
        SET referral_rewarded = TRUE
        WHERE telegram_id = %s
        AND referral_rewarded = FALSE
        RETURNING telegram_id
    """, (telegram_id,))

    changed = cur.fetchone()

    if not changed:
        return False

    cur.execute("""
        UPDATE users
        SET balance = balance + %s,
            referral_count = referral_count + 1
        WHERE telegram_id = %s
    """, (
        REFERRAL_REWARD,
        referred["referred_by"]
    ))

    return True


@app.get("/api/referrals")
def referral_list(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            telegram_id,
            first_name,
            username,
            referred_at,
            referral_rewarded
        FROM users
        WHERE referred_by = %s
        ORDER BY referred_at DESC
    """, (user["telegram_id"],))

    rows = cur.fetchall()

    now = datetime.now(timezone.utc)

    referrals = []

    approved = 0
    pending = 0
    expired = 0

    for row in rows:
        referred_at = row["referred_at"]

        if row["referral_rewarded"]:
            status = "approved"
            approved += 1

        elif (
            referred_at
            and now > referred_at + timedelta(hours=24)
        ):
            status = "expired"
            expired += 1

        else:
            status = "pending"
            pending += 1

        referrals.append({
            "telegram_id": row["telegram_id"],
            "first_name": row["first_name"],
            "username": row["username"],
            "referred_at": (
                referred_at.isoformat()
                if referred_at else None
            ),
            "status": status,
            "bonus": (
                float(REFERRAL_REWARD)
                if status == "approved"
                else 0
            )
        })

    cur.execute("""
        SELECT COALESCE(SUM(balance), 0) AS balance
        FROM users
        WHERE telegram_id = %s
    """, (user["telegram_id"],))

    cur.close()
    conn.close()

    return {
        "referral_link": (
            f"https://t.me/CherryMiningBot?start={user['telegram_id']}"
        ),
        "total": len(referrals),
        "approved": approved,
        "pending": pending,
        "expired": expired,
        "bonus_per_referral": float(REFERRAL_REWARD),
        "total_bonus": float(
            approved * REFERRAL_REWARD
        ),
        "referrals": referrals
    }


# ==================================================
# MINING
# ==================================================

@app.get("/api/mining/status")
def mining_status(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    require_channel(user["telegram_id"])

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM users
        WHERE telegram_id = %s
    """, (user["telegram_id"],))

    account = cur.fetchone()

    cur.close()
    conn.close()

    return {
        "success": True,
        **make_user_response(account)
    }


@app.post("/api/mining/start")
def mining_start(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    require_channel(user["telegram_id"])

    now = datetime.now(timezone.utc)
    end_time = now + timedelta(hours=MINING_HOURS)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM users
        WHERE telegram_id = %s
        FOR UPDATE
    """, (user["telegram_id"],))

    row = cur.fetchone()

    if row["mining_started"] and row["mining_ends"]:
        if row["mining_ends"] > now:
            conn.rollback()
            cur.close()
            conn.close()

            raise HTTPException(
                400,
                "Mining is already running"
            )

        remaining = mining_amount(row, now)

        if remaining > 0:
            conn.rollback()
            cur.close()
            conn.close()

            raise HTTPException(
                400,
                "Claim your previous mining reward first"
            )

    cur.execute("""
        UPDATE users
        SET mining_started = %s,
            mining_ends = %s,
            mining_claimed_at = %s
        WHERE telegram_id = %s
    """, (
        now,
        end_time,
        now,
        user["telegram_id"]
    ))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "mining_started": now.isoformat(),
        "mining_end_at": end_time.isoformat(),
        "reward": float(MINING_REWARD),
        "duration_hours": MINING_HOURS
    }


@app.post("/api/mining/claim")
def mining_claim(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    require_channel(user["telegram_id"])

    now = datetime.now(timezone.utc)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM users
        WHERE telegram_id = %s
        FOR UPDATE
    """, (user["telegram_id"],))

    row = cur.fetchone()

    if not row["mining_started"] or not row["mining_ends"]:
        conn.rollback()
        cur.close()
        conn.close()

        raise HTTPException(400, "Mining is not running")

    reward = mining_amount(row, now)

    if reward <= 0:
        conn.rollback()
        cur.close()
        conn.close()

        raise HTTPException(400, "No Cherry available to claim")

    cur.execute("""
        UPDATE users
        SET balance = balance + %s,
            mining_claimed_at = %s
        WHERE telegram_id = %s
    """, (
        reward,
        now,
        user["telegram_id"]
    ))

    if now >= row["mining_ends"]:
        cur.execute("""
            UPDATE users
            SET mining_started = NULL,
                mining_ends = NULL,
                mining_claimed_at = NULL
            WHERE telegram_id = %s
        """, (user["telegram_id"],))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "reward": float(reward),
        "usd_reward": float(usd_value(reward)),
        "message": "Cherry claimed successfully"
    }


# ==================================================
# DAILY BONUS
# ==================================================

@app.post("/api/daily/claim")
def daily_claim(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    require_channel(user["telegram_id"])

    now = datetime.now(timezone.utc)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT last_daily
        FROM users
        WHERE telegram_id = %s
        FOR UPDATE
    """, (user["telegram_id"],))

    row = cur.fetchone()

    if (
        row["last_daily"]
        and row["last_daily"] + timedelta(hours=24) > now
    ):
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Daily bonus is not ready")

    cur.execute("""
        UPDATE users
        SET balance = balance + %s,
            last_daily = %s
        WHERE telegram_id = %s
    """, (
        DAILY_REWARD,
        now,
        user["telegram_id"]
    ))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "reward": float(DAILY_REWARD),
        "usd_reward": float(usd_value(DAILY_REWARD))
    }


# ==================================================
# TASKS
# ==================================================

@app.get("/api/tasks")
def get_tasks(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    require_channel(user["telegram_id"])

    now = datetime.now(timezone.utc)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT task_id, MAX(claimed_at) AS last_claim
        FROM task_claims
        WHERE telegram_id = %s
        GROUP BY task_id
    """, (user["telegram_id"],))

    claimed = {
        row["task_id"]: row["last_claim"]
        for row in cur.fetchall()
    }

    cur.close()
    conn.close()

    result = []

    for task_id in range(1, 11):
        last_claim = claimed.get(task_id)

        completed = bool(
            last_claim
            and last_claim + timedelta(hours=24) > now
        )

        result.append({
            "id": task_id,
            "title": f"Daily Ad Task {task_id}",
            "description": "Watch a rewarded ad to earn Cherry.",
            "reward": float(TASK_REWARD),
            "completed": completed,
            "next_available_at": (
                (last_claim + timedelta(hours=24)).isoformat()
                if completed else None
            )
        })

    return {"tasks": result}


# ==================================================
# MONETAG AD SESSION
# ==================================================

@app.post("/api/ads/session")
def create_ad_session(
    x_telegram_init_data: str = Header(default=""),
    task_id: int = 1
):
    user = current_user(x_telegram_init_data)

    require_channel(user["telegram_id"])

    if task_id < 1 or task_id > 10:
        raise HTTPException(400, "Invalid task")

    session_id = secrets.token_urlsafe(18)
    ymid = "cm_" + secrets.token_hex(16)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO ad_sessions (
            id,
            ymid,
            telegram_id,
            task_id
        )
        VALUES (%s, %s, %s, %s)
    """, (
        session_id,
        ymid,
        user["telegram_id"],
        task_id
    ))

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

    require_channel(user["telegram_id"])

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT status
        FROM ad_sessions
        WHERE id = %s
        AND telegram_id = %s
    """, (
        session_id,
        user["telegram_id"]
    ))

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

    require_channel(user["telegram_id"])

    now = datetime.now(timezone.utc)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM ad_sessions
        WHERE id = %s
        AND telegram_id = %s
        AND task_id = %s
        FOR UPDATE
    """, (
        body.session_id,
        user["telegram_id"],
        task_id
    ))

    session = cur.fetchone()

    if not session or session["status"] != "valued":
        conn.rollback()
        cur.close()
        conn.close()

        raise HTTPException(
            400,
            "Verified ad reward not found"
        )

    cur.execute("""
        SELECT claimed_at
        FROM task_claims
        WHERE telegram_id = %s
        AND task_id = %s
        ORDER BY claimed_at DESC
        LIMIT 1
    """, (
        user["telegram_id"],
        task_id
    ))

    previous = cur.fetchone()

    if (
        previous
        and previous["claimed_at"] + timedelta(hours=24) > now
    ):
        conn.rollback()
        cur.close()
        conn.close()

        raise HTTPException(
            400,
            "Task already completed today"
        )

    cur.execute("""
        INSERT INTO task_claims (
            telegram_id,
            task_id,
            claimed_at
        )
        VALUES (%s, %s, %s)
    """, (
        user["telegram_id"],
        task_id,
        now
    ))

    cur.execute("""
        UPDATE users
        SET balance = balance + %s
        WHERE telegram_id = %s
    """, (
        TASK_REWARD,
        user["telegram_id"]
    ))

    cur.execute("""
        UPDATE ad_sessions
        SET status = 'claimed',
            rewarded_at = %s
        WHERE id = %s
    """, (
        now,
        body.session_id
    ))

    referral_approved = process_referral_reward(
        cur,
        user["telegram_id"],
        now
    )

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "reward": float(TASK_REWARD),
        "referral_approved": referral_approved,
        "referral_bonus": (
            float(REFERRAL_REWARD)
            if referral_approved else 0
        )
    }


# ==================================================
# MONETAG POSTBACK
# ==================================================

@app.get("/postback/monetag")
def monetag_postback(
    secret: str = "",
    ymid: str = "",
    event_type: str = "",
    reward_event_type: str = "",
    estimated_price: float = 0
):
    if not MONETAG_SECRET:
        raise HTTPException(
            500,
            "MONETAG_SECRET is not configured"
        )

    if not hmac.compare_digest(secret, MONETAG_SECRET):
        raise HTTPException(403, "Invalid postback secret")

    if not ymid or event_type not in ("impression", "click"):
        raise HTTPException(400, "Invalid postback")

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM ad_sessions
        WHERE ymid = %s
        FOR UPDATE
    """, (ymid,))

    session = cur.fetchone()

    if not session:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(404, "Unknown ad session")

    cur.execute("""
        INSERT INTO ad_events (
            ymid,
            event_type,
            reward_event_type,
            estimated_price
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (ymid, event_type)
        DO NOTHING
    """, (
        ymid,
        event_type,
        reward_event_type,
        estimated_price
    ))

    if (
        event_type == "impression"
        and reward_event_type == "valued"
    ):
        cur.execute("""
            UPDATE ad_sessions
            SET status = 'valued'
            WHERE ymid = %s
            AND status = 'pending'
        """, (ymid,))

    elif (
        event_type == "impression"
        and reward_event_type == "non_valued"
    ):
        cur.execute("""
            UPDATE ad_sessions
            SET status = 'rejected'
            WHERE ymid = %s
            AND status = 'pending'
        """, (ymid,))

    conn.commit()
    cur.close()
    conn.close()

    return {"received": True}


# ==================================================
# WALLET
# ==================================================

@app.post("/api/wallet")
def save_wallet(
    body: WalletBody,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    if not valid_bsc_address(body.address):
        raise HTTPException(400, "Invalid BNB wallet address")

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET wallet_address = %s,
            wallet_verified = FALSE
        WHERE telegram_id = %s
    """, (
        body.address,
        user["telegram_id"]
    ))

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
        INSERT INTO wallet_challenges (
            telegram_id,
            address,
            message,
            expires_at
        )
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
        SELECT *
        FROM wallet_challenges
        WHERE telegram_id = %s
        FOR UPDATE
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

        raise HTTPException(
            400,
            "Invalid or expired wallet challenge"
        )

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

        raise HTTPException(
            400,
            "Wallet signature does not match"
        )

    cur.execute("""
        UPDATE users
        SET wallet_address = %s,
            wallet_verified = TRUE
        WHERE telegram_id = %s
    """, (
        body.address,
        user["telegram_id"]
    ))

    cur.execute("""
        DELETE FROM wallet_challenges
        WHERE telegram_id = %s
    """, (user["telegram_id"],))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "verified": True
    }


# ==================================================
# WITHDRAWAL
# ==================================================

@app.post("/api/withdraw")
def create_withdrawal(
    body: WithdrawBody,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    if body.network != "BEP20":
        raise HTTPException(
            400,
            "Only BNB Smart Chain BEP20 is supported"
        )

    if not valid_bsc_address(body.wallet_address):
        raise HTTPException(400, "Invalid wallet address")

    if body.amount < MIN_WITHDRAW:
        raise HTTPException(
            400,
            "Minimum withdrawal is 10,000 Cherry"
        )

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM users
        WHERE telegram_id = %s
        FOR UPDATE
    """, (user["telegram_id"],))

    account = cur.fetchone()

    if not account["wallet_address"]:
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(400, "Save your wallet first")

    if (
        account["wallet_address"].lower()
        != body.wallet_address.lower()
    ):
        conn.rollback()
        cur.close()
        conn.close()
        raise HTTPException(
            400,
            "Wallet does not match saved wallet"
        )

    cur.execute("""
        SELECT COUNT(*) AS total
        FROM withdrawals
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

    if as_decimal(account["balance"]) < body.amount:
        conn.rollback()
        cur.close()
        conn.close()

        raise HTTPException(400, "Insufficient Cherry balance")

    cur.execute("""
        UPDATE users
        SET balance = balance - %s
        WHERE telegram_id = %s
    """, (
        body.amount,
        user["telegram_id"]
    ))

    cur.execute("""
        INSERT INTO withdrawals (
            telegram_id,
            amount,
            wallet_address,
            network
        )
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
def withdrawal_history(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            amount,
            wallet_address,
            network,
            status,
            tx_hash,
            created_at
        FROM withdrawals
        WHERE telegram_id = %s
        ORDER BY created_at DESC
        LIMIT 50
    """, (user["telegram_id"],))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return {
        "withdrawals": [
            {
                **dict(row),
                "amount": float(row["amount"]),
                "created_at": row["created_at"].isoformat()
            }
            for row in rows
        ]
    }


# ==================================================
# ADMIN WITHDRAWAL MANAGEMENT
# ==================================================

@app.get("/api/admin/withdrawals")
def admin_withdrawals(
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)
    require_admin(user["telegram_id"])

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM withdrawals
        WHERE status = 'pending'
        ORDER BY created_at ASC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return {
        "withdrawals": [
            {
                **dict(row),
                "amount": float(row["amount"]),
                "created_at": row["created_at"].isoformat()
            }
            for row in rows
        ]
    }


@app.post("/api/admin/withdrawals/{withdrawal_id}/approve")
def approve_withdrawal(
    withdrawal_id: int,
    body: ApproveBody,
    x_telegram_init_data: str = Header(default="")
):
    user = current_user(x_telegram_init_data)
    require_admin(user["telegram_id"])

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE withdrawals
        SET status = 'approved',
            tx_hash = %s,
            processed_at = NOW()
        WHERE id = %s
        AND status = 'pending'
        RETURNING id
    """, (
        body.tx_hash,
        withdrawal_id
    ))

    result = cur.fetchone()

    if not result:
        conn.rollback()
        cur.close()
        conn.close()

        raise HTTPException(
            404,
            "Pending withdrawal not found"
        )

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "status": "approved"
    }


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
        SELECT telegram_id, amount
        FROM withdrawals
        WHERE id = %s
        AND status = 'pending'
        FOR UPDATE
    """, (withdrawal_id,))

    row = cur.fetchone()

    if not row:
        conn.rollback()
        cur.close()
        conn.close()

        raise HTTPException(
            404,
            "Pending withdrawal not found"
        )

    cur.execute("""
        UPDATE withdrawals
        SET status = 'rejected',
            processed_at = NOW()
        WHERE id = %s
    """, (withdrawal_id,))

    cur.execute("""
        UPDATE users
        SET balance = balance + %s
        WHERE telegram_id = %s
    """, (
        row["amount"],
        row["telegram_id"]
    ))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "status": "rejected"
    }


# ==================================================
# END
# ==================================================

