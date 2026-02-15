# Python Bot Smoke Checklist

## Prerequisites

- `docker compose up -d --build`
- Services are up: `docker compose ps`
- Bot logs clean: `docker compose logs --tail=100 bot`

## 1) Start/Menu

- [ ] Send `/start`
- [ ] Confirm main menu appears
- [ ] Send `/menu`
- [ ] Confirm same menu appears

## 2) Login flow

- [ ] Tap `📱 Login`
- [ ] Send phone as text in international format
- [ ] Confirm code prompt appears
- [ ] Send code with spaces (example: `1 2 3 4 5`)
- [ ] If 2FA required, send password and confirm login success

## 3) Group flow

- [ ] Tap `👥 Groups`
- [ ] Tap `➕ Add groups`
- [ ] Import one remote group
- [ ] Confirm group appears in selected list

## 4) Message + interval setup

- [ ] Tap `📮 Message`
- [ ] Send broadcast text
- [ ] Choose preset interval (`3/5/10/30`)
- [ ] Confirm activation message appears

## 5) Start/Stop broadcast

- [ ] Tap `▶ Start`
- [ ] Confirm enabled response
- [ ] Tap `⏸ Stop`
- [ ] Confirm stopped response

## 6) Admin flow (super admin user)

- [ ] Open `🔑 Admin Panel`
- [ ] Open one user detail
- [ ] Test `+30 kun` and `-30 kun`
- [ ] Test `📣 Barchaga xabar`

## 7) Runtime checks

- [ ] Worker logs show no critical exceptions
- [ ] App health endpoint responds: `GET /health`
- [ ] Queue jobs process without per-user lock violation warnings

## 8) Staged rollout checks (1 -> 2 -> 4 workers)

- [ ] Run with 1 worker for 15-30 minutes and record p95 lag
- [ ] Run with 2 workers for 15-30 minutes and compare p95 lag/error outcomes
- [ ] Run with 4 workers for 15-30 minutes and compare p95 lag/error outcomes
- [ ] Confirm `no-account` and `provider-constrained-delay` outcomes are within expected range
