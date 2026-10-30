
# Cherry Mining 🍒

Cherry Mining is a Telegram Mini App with a reward-based mining system.

## Features

- Telegram Mini App authentication
- 24-hour mining cycle
- Mining rewards
- Daily check-in bonus
- 10 recurring ad tasks
- Referral system
- Cherry balance with USD equivalent
- BNB Smart Chain (BEP20) wallet
- Wallet signature verification
- Minimum withdrawal: 10,000 Cherry ($1)
- Manual withdrawal approval
- Neon PostgreSQL database
- FastAPI backend

## Technology

- Python
- FastAPI
- PostgreSQL (Neon)
- HTML
- CSS
- JavaScript
- Telegram Web Apps

## Configuration

Set these environment variables in Render:

- BOT_TOKEN
- DATABASE_URL
- ADMIN_TELEGRAM_IDS
- MINING_REWARD
- REFERRAL_REWARD
- TASK_REWARD
- MONETAG_SECRET

Never upload your real secrets to GitHub.

## Local Installation

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the backend:

```bash
uvicorn main:app --reload
```

## Deployment

Deploy this repository using Render.

The service starts with:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Important

- Rewards must be verified on the server.
- Never trust browser-side reward claims.
- Monetag postback must be configured correctly.
- Withdrawals require manual admin approval.
- Wallet verification uses a signature, not a payment.

## Project

Cherry Mining Telegram Bot

Bot: @CherryMiningBot
