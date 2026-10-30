from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

app = FastAPI(title="Cherry Mining Demo")
users = {}

@app.get("/")
def home(): return FileResponse("index.html")
@app.get("/style.css")
def css(): return FileResponse("style.css", media_type="text/css")
@app.get("/app.js")
def js(): return FileResponse("app.js", media_type="application/javascript")

def identify(init_data):
    # Production use requires Telegram initData signature validation.
    if not init_data:
        raise HTTPException(status_code=401, detail="Telegram Mini App থেকে খুলুন।")
    return "demo-user"

@app.get("/api/me")
def me(x_telegram_init_data: str | None = Header(default=None)):
    uid=identify(x_telegram_init_data)
    u=users.setdefault(uid, {"balance":0,"mining":False,"referrals":0})
    return {"balance":u["balance"],"mining_active":u["mining"],"referral_count":u["referrals"],"referral_link":"https://t.me/CherryMiningBot"}

@app.post("/api/mining/start")
def start(x_telegram_init_data: str | None = Header(default=None)):
    u=users.setdefault(identify(x_telegram_init_data), {"balance":0,"mining":False,"referrals":0})
    u["mining"]=True
    return {"ok":True,"message":"Demo mining started."}

@app.post("/api/mining/claim")
def claim(x_telegram_init_data: str | None = Header(default=None)):
    u=users.setdefault(identify(x_telegram_init_data), {"balance":0,"mining":False,"referrals":0})
    if not u["mining"]: raise HTTPException(status_code=400, detail="আগে Mining Start করুন।")
    u["balance"]+=500
    return {"ok":True,"message":"500 demo Cherry যোগ হয়েছে।"}

@app.post("/api/daily/claim")
def daily(x_telegram_init_data: str | None = Header(default=None)):
    u=users.setdefault(identify(x_telegram_init_data), {"balance":0,"mining":False,"referrals":0})
    u["balance"]+=100
    return {"ok":True,"message":"100 demo Cherry যোগ হয়েছে।"}

@app.get("/health")
def health(): return {"status":"ok"}
