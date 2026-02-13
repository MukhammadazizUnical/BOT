# NEW BOT (Python rewrite)

This folder is a Python rewrite of the existing Node.js SEND_BOT with app/worker split, queue-driven broadcasts, flood-safe retries, and persistent attempt lifecycle.

## Quick start

1. Copy env:

```bash
cp .env.example .env
```

2. Start stack:

```bash
docker compose up -d --build
```

3. Check logs:

```bash
docker compose logs -f app worker bot
```

## Processes

- `app`: FastAPI API + scheduler loop
- `worker`: ARQ broadcast processor
- `bot`: Telegram bot UI handlers

## Notes

- DB tables are created at app startup for first run.
- For production, move to Alembic migrations.
