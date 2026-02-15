## Why

Broadcast runs currently generate inconsistent timing under load, especially with low worker counts and many active users. We need deterministic interval behavior and queue execution that can sustain around 1000 concurrent broadcasters without skipping valid sends or producing noisy stale/empty runs.

## What Changes

- Enforce strict interval scheduling semantics so a campaign does not run earlier than configured and does not drift due to scheduler bookkeeping or duplicate enqueue races.
- Improve low-worker fairness and throughput by controlling per-user queue pressure, reducing wasted jobs, and prioritizing runnable campaigns.
- Ensure campaigns with unavailable Telegram accounts are paused/de-prioritized instead of repeatedly consuming worker capacity.
- Clarify processor success/failure contract so retries/continuations happen only for actionable states and operational logs are meaningful.
- Add observability for timing compliance (scheduled vs actual run lag) and skip reasons to support production tuning.

## Capabilities

### New Capabilities
- `broadcast-interval-guarantees`: Define enforceable timing guarantees and acceptance criteria for interval-based broadcast execution under low-worker/high-user conditions.

### Modified Capabilities
- `broadcast-dispatch-queue`: Tighten enqueue and continuation behavior to reduce duplicate/non-actionable jobs and preserve fairness across users.
- `broadcast-delivery-state`: Update delivery state transitions for interval resets, retry windows, and no-account scenarios.
- `nodejs-parity-broadcast-runtime`: Align runtime semantics with expected parity behavior while keeping stable interval execution in Python.
- `telegram-flood-retry`: Refine retry/flood-wait interaction so backoff does not break interval guarantees more than provider-imposed constraints.

## Impact

- Affected code: `NEW BOT/app/services/scheduler_service.py`, `NEW BOT/app/services/broadcast_processor_service.py`, `NEW BOT/app/services/userbot_service.py`, `NEW BOT/app/services/broadcast_queue_service.py`, related tests.
- Affected systems: Redis queue behavior, ARQ worker throughput, PostgreSQL attempt lifecycle state.
- Operational impact: updated environment tuning guidance for low worker deployments (1-4 workers) with large user counts.
