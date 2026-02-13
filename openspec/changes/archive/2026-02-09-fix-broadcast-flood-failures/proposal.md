## Why

When 30-40 users trigger broadcast at the same time, the bot misroutes timing and reports flood failures even when the user account has not actually delivered messages. This causes unreliable broadcast behavior and user confusion, so we need deterministic queueing and accurate delivery/failure state now.

## What Changes

- Introduce controlled broadcast execution with per-account concurrency limits and ordered dispatch.
- Add rate-limit aware retry handling for Telegram flood responses (including backoff from `retry_after` and jitter).
- Add authoritative delivery state tracking so a message is only marked failed after terminal conditions.
- Add observability for broadcast attempts, retries, queue lag, and final outcomes.
- Define safeguards to prevent duplicate sends and cross-user interference during high load.

## Capabilities

### New Capabilities

- `broadcast-dispatch-queue`: Queue-based broadcast scheduling with per-sender isolation, concurrency control, and predictable ordering.
- `telegram-flood-retry`: Flood/rate-limit detection with bounded retry policy and compliant backoff behavior.
- `broadcast-delivery-state`: Persistent attempt lifecycle and final status transitions (`pending`, `in-flight`, `sent`, `failed-terminal`).

### Modified Capabilities

- None.

## Impact

- Affected areas: broadcast worker/runner logic, send pipeline, persistence layer for attempt state, and job scheduling.
- APIs/contracts: internal broadcast status and progress reporting may expand to include retry metadata and terminal-failure reason codes.
- Dependencies/systems: messaging platform rate-limit behavior, queue backend, and logging/metrics pipeline.
