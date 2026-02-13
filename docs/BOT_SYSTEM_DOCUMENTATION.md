# SEND_BOT System Documentation

This document is a full technical reference of the current Telegram broadcast bot implementation in this repository.

## 1) Project Summary

`SEND_BOT` is a NestJS-based Telegram system with two runtime roles:

- `app` role: runs Telegraf bot UI + scheduler.
- `worker` role: runs BullMQ broadcast processor.

Main goals:

- Let authorized users connect Telegram user accounts (session string flow).
- Let users import target groups and configure auto-broadcast intervals.
- Execute broadcasts with queueing, retry, flood-aware behavior, and persistence.
- Provide admin controls for access lifecycle and announcements.

## 2) Tech Stack

- Runtime: Node.js + TypeScript (NestJS).
- Bot framework: `nestjs-telegraf` + `telegraf`.
- Telegram user sessions: `telegram` (gramjs client).
- Queue: BullMQ.
- Database: PostgreSQL via Prisma.
- Cache/lock transport: Redis.
- Deployment: Docker Compose (`bot`, `worker`, `postgres`, `redis`).

## 3) High-Level Architecture

### Components

- `src/app.module.ts`
  - Global config loading.
  - Redis connection setup (from `REDIS_URL` / `UPSTASH_REDIS_URL` or host+port).
  - Telegraf bootstrap; disabled update loop on `worker` role.
  - Imports `BotModule`.

- `src/bot/bot.module.ts`
  - Registers BullMQ queue `broadcast`.
  - Default job options (`attempts`, exponential backoff, cleanup policy).
  - Registers provider list; includes `BroadcastProcessor` only on worker role.

- `src/main.ts`
  - Starts Nest app.
  - Ignores known noisy `TIMEOUT` update-loop process-level errors from gramjs update stack.

### Runtime Roles

- `BOT_ROLE=app`
  - Telegraf launch is enabled.
  - Scheduler loop is enabled.
  - Processor is not registered.

- `BOT_ROLE=worker`
  - Telegraf launch is disabled (`launchOptions: false`).
  - Scheduler is disabled.
  - Queue processor is active and executes send jobs.

## 4) Core Services

### `BotService` (`src/bot/bot.service.ts`)

Responsibilities:

- User interaction via inline menus and commands.
- Access control middleware (whitelist + expiry model).
- Login state machine and temporary in-memory UI state maps.
- Group import UI and local group activation management.
- Broadcast setup UX (message + interval) and start/stop controls.
- Admin panel actions (`adduser`, `ban`, announcements, expiry adjustments).

State machine enum:

- `IDLE`
- `WAITING_PHONE`
- `WAITING_CODE`
- `WAITING_PASSWORD`
- `WAITING_BROADCAST_MSG`
- `WAITING_ADMIN_ANNOUNCE`
- `WAITING_INTERVAL`

Important behavior:

- Wraps Telegram calls with retry on transient network errors.
- Handles stale callback queries safely.
- Provides safe message deletion/edit behavior for UI transitions.

### `UserbotService` (`src/bot/userbot.service.ts`)

Responsibilities:

- Telegram user-account login flow (`startLogin`, `completeLogin`, `complete2FA`).
- Persistent/reusable gramjs clients per Telegram account.
- Remote group discovery from user dialogs, with cache + single-flight.
- Broadcast execution engine with persistent attempts and retry logic.

Broadcast engine features:

- Fetch active Telegram accounts for owner user.
- Seed campaign attempts idempotently into `BroadcastAttempt`.
- Recover stuck `in-flight` attempts.
- Apply global rate limiting and per-account pacing.
- Flood/retriable detection and `nextAttemptAt` scheduling.
- Terminal failure classification and reason code persistence.
- Metrics snapshot + alert logging.
- Micro-batch budget per processor run (`BROADCAST_ATTEMPTS_PER_JOB`).

Remote group fetch pressure controls:

- Cache TTL (`REMOTE_GROUPS_CACHE_TTL_MS`).
- Min refresh window (`REMOTE_GROUPS_MIN_REFRESH_MS`).
- Failure cooldown (`REMOTE_GROUPS_FAILURE_COOLDOWN_MS`).
- Single-flight dedupe per user.

### `SchedulerService` (`src/bot/scheduler.service.ts`)

Responsibilities:

- Periodically checks due `BroadcastConfig` rows.
- Creates queue jobs in bulk (`addBulk`).
- Uses distributed Redis lock to avoid duplicate scheduler loops across app instances.
- Applies deterministic per-user enqueue jitter (`SCHEDULER_JITTER_MAX_MS`).
- Updates `lastRunAt` only for successfully queued configs.

### `BroadcastProcessor` (`src/bot/broadcast.processor.ts`)

Responsibilities:

- Consumes queue jobs from `broadcast` queue.
- Enforces per-user Redis lock while processing a job.
- Calls `UserbotService.broadcastMessage(...)` with a run budget.
- On deferred-but-healthy state (pending/in-flight only), enqueues continuation job with jitter delay.

Continuation controls:

- `BROADCAST_CONTINUATION_BASE_DELAY_MS`
- `BROADCAST_CONTINUATION_JITTER_MS`

### Supporting Services

- `GroupService`: CRUD/upsert for `UserGroup`.
- `SessionService`: legacy session helpers; current login state mostly references `TelegramAccount` active sessions.
- `PrismaService`: Prisma lifecycle connection management.
- `BotController`: HTTP send endpoints (`/bot/send`, `/bot/send-bot`).

## 5) Queue + Broadcast Lifecycle

### 5.1 Scheduling

1. Scheduler loop runs every `SCHEDULER_CHECK_INTERVAL_MS`.
2. Due configs are queried by interval + `lastRunAt` window (`EARLY_FACTOR` applied).
3. One job per due config is enqueued with stable `jobId` per run slot (`bc-<configId>-<runSlot>`).
4. Deterministic delay spreads bursts across users in same slot.

### 5.2 Processing

1. Worker receives job (`userId`, `message`, `campaignId`, `queuedAt`).
2. Acquires user lock (`broadcast:user-lock:<userId>`).
3. Executes micro-batch broadcast run (attempt budget).
4. If campaign not finished but no terminal failure, schedules continuation job.
5. Releases user lock.

### 5.3 Attempt Lifecycle (`BroadcastAttempt`)

Statuses:

- `pending`: waiting to be claimed.
- `in-flight`: claimed and currently being sent.
- `sent`: delivered successfully.
- `failed-terminal`: final failure.

Retry behavior:

- Retriable errors (`FLOOD_WAIT`, timeout-like signals) return attempt to `pending` with `nextAttemptAt`.
- Retry delay uses exponential/backoff + optional provider `retry_after` + jitter.
- Exceeded retry budget marks attempt `failed-terminal` with terminal reason.

Idempotency:

- `idempotencyKey = campaignId:targetGroupId`.
- Unique constraints prevent duplicate attempts for same campaign target.

## 6) Data Model (Prisma)

Defined in `prisma/schema.prisma`.

Key models:

- `User`: owner identity (telegram id as string).
- `TelegramAccount`: linked user account sessions and flood flags.
- `UserGroup`: target group list per user (composite PK `userId + id`).
- `BroadcastConfig`: one row per user (`message`, `interval`, `isActive`, `lastRunAt`).
- `BroadcastAttempt`: durable per-target execution state for each campaign.
- `AllowedUser`: access whitelist with expiry model.
- `SentMessage`: history records used by UI.
- `Session`: legacy helper table.
- `BroadcastTargetUser`: additional target entity table (not central to current group flow).

Important constraints/indexes:

- `BroadcastConfig.userId` unique.
- `BroadcastAttempt.idempotencyKey` unique.
- `BroadcastAttempt` also unique on `(campaignId, targetGroupId)`.
- Indexed fields for campaign status scans.

## 7) User Flows

### Login Flow

1. User chooses login.
2. Sends phone/contact.
3. Bot requests code via gramjs.
4. User submits code.
5. If 2FA needed, user submits password.
6. Session string is persisted in `TelegramAccount`.

### Group Import Flow

1. User opens group selection.
2. Bot fetches remote groups via user account dialogs.
3. Remote groups are deduped and paginated.
4. User toggles add/remove in local `UserGroup` list.

### Broadcast Setup Flow

1. User sends message text.
2. User picks interval (preset or custom).
3. Bot saves/updates `BroadcastConfig` and activates it.
4. Scheduler starts periodic queueing.

## 8) Access and Admin Model

Access gates:

- Super admins by username list in code.
- Others must exist in `AllowedUser` and not be expired.
- Unknown users are auto-created as pending (`expiresAt = epoch`) and denied until approved.

Admin features:

- `/adduser <id> <days>`.
- `/ban <id>`.
- `/info`, `/id`.
- Inline admin panel with requested/confirmed/all filters.
- Quick expiry add/subtract.
- Broadcast announcement to all allowed users.

## 9) HTTP Endpoints

Controller: `src/bot/bot.controller.ts`

- `POST /bot/send`
  - If `userId` is absent: sends via Bot API (`BotService.sendTelegramMessage`).
  - If `userId` present: sends via userbot account (`UserbotService.sendMessageToUser`).
  - Optional `telegramAccountId` override.

- `POST /bot/send-bot`
  - Always sends via Bot API.

DTO:

- `to: string` (required)
- `message: string` (required)
- `userId?: number`
- `telegramAccountId?: string`

## 10) Environment Variables Reference

### Telegram/Auth

- `TG_BOT_TOKEN`
- `TG_API_ID`
- `TG_API_HASH`
- `TG_MANUAL_VIDEO_ID`
- `TG_ANNOUNCE_STICKER_ID`

### Runtime/HTTP

- `PORT`
- `BOT_ROLE` (`app` or `worker`)

### Database/Redis

- `DATABASE_URL`
- `REDIS_URL`
- `UPSTASH_REDIS_URL`
- `REDIS_HOST`
- `REDIS_PORT`

### Queue/Worker

- `BROADCAST_CONCURRENCY`
- `BROADCAST_JOB_ATTEMPTS`
- `BROADCAST_JOB_BACKOFF_MS`
- `BROADCAST_USER_LOCK_TTL_MS`

### Scheduler

- `SCHEDULER_CHECK_INTERVAL_MS`
- `SCHEDULER_EARLY_FACTOR`
- `SCHEDULER_MAX_DUE_PER_TICK`
- `SCHEDULER_JITTER_MAX_MS`

### Broadcast Throughput/Fairness

- `BROADCAST_PER_ACCOUNT_CONCURRENCY`
- `BROADCAST_ATTEMPTS_PER_JOB`
- `BROADCAST_CONTINUATION_BASE_DELAY_MS`
- `BROADCAST_CONTINUATION_JITTER_MS`

### Telegram Safety / Rate

- `TELEGRAM_PER_ACCOUNT_MPM`
- `TELEGRAM_PER_ACCOUNT_MIN_DELAY_MS`
- `TELEGRAM_GLOBAL_MPS`

### Retry/Alerting

- `BROADCAST_MAX_RETRIES`
- `BROADCAST_RETRY_BASE_MS`
- `BROADCAST_RETRY_MAX_MS`
- `BROADCAST_RETRY_JITTER_RATIO`
- `BROADCAST_INFLIGHT_STUCK_MS`
- `BROADCAST_RETRY_STORM_THRESHOLD`
- `BROADCAST_STUCK_INFLIGHT_THRESHOLD`
- `BROADCAST_QUEUE_LAG_ALERT_MS`

### Remote Group Fetch Pressure

- `REMOTE_GROUPS_CACHE_TTL_MS`
- `REMOTE_GROUPS_MIN_REFRESH_MS`
- `REMOTE_GROUPS_FAILURE_COOLDOWN_MS`

## 11) Docker Deployment Notes

`docker-compose.yml` defines:

- `bot` (app role)
- `worker` (worker role)
- `postgres`
- `redis`

Both `bot` and `worker` run:

- `npx prisma db push && npm run start:prod`

Operationally recommended:

- Scale `worker` service for throughput (instead of only inflating a single process too much).
- Keep `BROADCAST_PER_ACCOUNT_CONCURRENCY=1` unless carefully tested.
- Tune `BROADCAST_ATTEMPTS_PER_JOB` and scheduler/continuation jitter to balance fairness and latency.

## 12) Logging and Observability

Structured events emitted by broadcast engine include:

- `enqueue`
- `dequeue`
- `sent`
- `retry_scheduled`
- `retry_exhausted`
- `terminal_failure`
- `recovered_stuck_in_flight`
- `batch_processed`
- `metrics_snapshot`

Alert logs include:

- retry storm threshold crossed.
- stuck in-flight threshold crossed.
- high queue lag.

## 13) Tests

Relevant tests:

- `src/bot/broadcast.integration.spec.ts`
- `src/bot/broadcast-orchestrator.util.spec.ts`
- `src/bot/userbot.service.spec.ts`

Coverage includes:

- retry -> sent lifecycle behavior.
- micro-batch continuation behavior.
- orchestrator utility classification/planning functions.

## 14) Known Constraints and Risks

- Telegram rate limits are the hard throughput ceiling.
- Strict exact-time delivery for large synchronized workloads is limited by provider constraints.
- Very high concurrency can overload CPU/DB/Redis before improving delivery.
- Session validity and account health directly impact delivery success.

## 15) Quick Operational Checklist

1. Confirm `BOT_ROLE` split (`app` vs `worker`) is correct.
2. Verify Redis and PostgreSQL connectivity.
3. Check scheduler queue logs (`queued`, `failed`).
4. Check worker logs for flood wait and retry storm patterns.
5. Tune gradually: concurrency, batch size, jitter, and per-account rate.
