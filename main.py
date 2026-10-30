import os
import hmac
import hashlib
import json
import time
from urllib.parse import parse_qsl
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DATABASE_URL = os.getenv("DATABASE_URL", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
MINING_PER_DAY = 500
CHERRY_PER_USD = 10000
AD_REWARD = 100
AD_COOLDOWN_SECONDS = 24 * 60 * 60
MIN_WITHDRAWAL = 10000

pool = None

async def init_db():
    global pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is missing")
    pool = await asyncpg.create_pool(DATABASE_URL, ssl="require")
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
          telegram_id BIGINT PRIMARY KEY,
          username TEXT,
          first_name TEXT,
          balance BIGINT NOT NULL DEFAULT 0,
          mining_started_at TIMESTAMPTZ,
          last_mining_claim_at TIMESTAMPTZ,
          last_watch_ad_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS transactions (
          id BIGSERIAL PRIMARY KEY,
          telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
          kind TEXT NOT NULL,
          amount BIGINT NOT NULL,
          note TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS ad_events (
          id BIGSERIAL PRIMARY KEY,
          telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
          placement TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          provider_event_id TEXT UNIQUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          verified_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id SERIAL PRIMARY KEY,
          title TEXT NOT NULL,
          reward BIGINT NOT NULL DEFAULT 0,
          is_active BOOLEAN NOT NULL DEFAULT TRUE
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
          id BIGSERIAL PRIMARY KEY,
          telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
          amount BIGINT NOT NULL,
          method TEXT NOT NULL,
          wallet_address TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        count = await conn.fetchval("SELECT COUNT(*) FROM tasks")
        if count == 0:
            titles = [
                "Join Telegram Channel", "Join Telegram Group", "Follow Social Page",
                "Watch Monetag Ad", "Daily Check-in", "Invite a Friend",
                "Read Project Rules", "Visit Partner Page", "Complete Profile",
                "Community Activity"
            ]
            for title in titles:
                await conn.execute(
                    "INSERT INTO tasks(title,reward) VALUES($1,0)", title
                )

def validate_telegram_init_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(503, "Bot authentication is not configured")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Missing Telegram initData hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise HTTPException(401, "Invalid Telegram initData")
    auth_date = int(pairs.get("auth_date", "0"))
    if time.time() - auth_date > 86400:
        raise HTTPException(401, "Telegram session expired. Reopen the Mini App.")
    try:
        return json.loads(pairs["user"])
    except Exception:
        raise HTTPException(401, "Telegram user data is missing")

async def current_user(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_telegram_init_data(init_data)
    tg_id = int(user["id"])
    async with pool.acquire() as conn:
        await conn.execute("""
          INSERT INTO users(telegram_id,username,first_name)
          VALUES($1,$2,$3)
          ON CONFLICT(telegram_id) DO UPDATE SET
          username=EXCLUDED.username, first_name=EXCLUDED.first_name
        """, tg_id, user.get("username"), user.get("first_name"))
    return user

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    if pool:
        await pool.close()

app = FastAPI(title="Cherry Mining API", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def home():
    return FileResponse("static/index.html")

@app.get("/health")
async def health():
    return {"ok": True, "service": "Cherry Mining API"}

@app.get("/api/me")
async def me(request: Request):
    user = await current_user(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
          SELECT telegram_id,username,first_name,balance,mining_started_at,
                 last_mining_claim_at,last_watch_ad_at
          FROM users WHERE telegram_id=$1
        """, int(user["id"]))
    return dict(row)

@app.post("/api/mining/start")
async def start_mining(request: Request):
    user = await current_user(request)
    async with pool.acquire() as conn:
        await conn.execute("""
          UPDATE users SET mining_started_at=COALESCE(mining_started_at,NOW())
          WHERE telegram_id=$1
        """, int(user["id"]))
    return {"ok": True, "message": "Mining started"}

@app.get("/api/tasks")
async def get_tasks(request: Request):
    await current_user(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id,title,reward FROM tasks WHERE is_active=TRUE ORDER BY id")
    return [dict(r) for r in rows]

@app.post("/api/ads/start")
async def ad_start(request: Request):
    user = await current_user(request)
    body = await request.json()
    placement = body.get("placement")
    if placement not in ("watch_ad", "mining_claim"):
        raise HTTPException(400, "Unknown ad placement")
    async with pool.acquire() as conn:
        event_id = await conn.fetchval("""
          INSERT INTO ad_events(telegram_id,placement,status)
          VALUES($1,$2,'pending') RETURNING id
        """, int(user["id"]), placement)
    # SDK promise success is NOT treated as provider-side proof of completion.
    return {"event_id": event_id, "status": "pending",
            "message": "Ad session recorded. Reward waits for provider verification."}

@app.post("/api/ads/complete")
async def ad_complete(request: Request):
    # Intentionally disabled until Monetag provides a documented, server-verifiable
    # callback/postback for this exact rewarded format.
    raise HTTPException(501, "Reward credit is disabled until Monetag server-side completion verification is configured.")

@app.post("/api/withdrawals")
async def create_withdrawal(request: Request):
    user = await current_user(request)
    body = await request.json()
    amount = int(body.get("amount", 0))
    method = str(body.get("method", "")).strip()
    address = str(body.get("wallet_address", "")).strip()
    if amount < MIN_WITHDRAWAL:
        raise HTTPException(400, "Minimum withdrawal is 10,000 Cherry")
    if not method or not address:
        raise HTTPException(400, "Withdrawal method and wallet address are required")
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT balance FROM users WHERE telegram_id=$1 FOR UPDATE", int(user["id"]))
            if row["balance"] < amount:
                raise HTTPException(400, "Insufficient balance")
            await conn.execute("UPDATE users SET balance=balance-$1 WHERE telegram_id=$2", amount, int(user["id"]))
            await conn.execute("""
              INSERT INTO withdrawals(telegram_id,amount,method,wallet_address)
              VALUES($1,$2,$3,$4)
            """, int(user["id"]), amount, method, address)
            await conn.execute("""
              INSERT INTO transactions(telegram_id,kind,amount,note)
              VALUES($1,'withdrawal',$2,'Withdrawal request')
            """, int(user["id"]), -amount)
    return {"ok": True, "message": "Withdrawal request submitted for admin review"}

@app.get("/api/config")
async def config():
    return {"mining_cherry_per_day": MINING_PER_DAY,
            "cherry_per_usd": CHERRY_PER_USD,
            "ad_reward": AD_REWARD,
            "ad_cooldown_seconds": AD_COOLDOWN_SECONDS,
            "minimum_withdrawal": MIN_WITHDRAWAL}
