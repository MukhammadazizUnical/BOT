## 1. Queue Partitioning and Dispatch Controls

- [x] 1.1 Add sender/account partition key to broadcast job enqueue path.
- [x] 1.2 Implement per-account worker lanes with configurable per-account concurrency.
- [x] 1.3 Add global dispatch concurrency limiter applied before send execution.
- [x] 1.4 Persist deterministic recipient ordering metadata and resume pointer.
- [x] 1.5 Add recovery logic to resume from next unsent recipient after restart.

## 2. Flood-Aware Retry Orchestration

- [x] 2.1 Add Telegram error classifier for retriable flood/rate-limit responses.
- [x] 2.2 Implement retry scheduler that honors provider `retry_after` when present.
- [x] 2.3 Add bounded jitter and configurable max retry attempts per send attempt.
- [x] 2.4 Mark attempts `failed-terminal` with `retry-exhausted` after retry budget is spent.

## 3. Delivery State Persistence and Idempotency

- [x] 3.1 Create/extend storage schema for attempt states (`pending`, `in-flight`, `sent`, `failed-terminal`) and timestamps.
- [x] 3.2 Implement atomic state transitions in send orchestrator.
- [x] 3.3 Add deterministic idempotency key generation for campaign-recipient attempts.
- [x] 3.4 Enforce de-duplication checks to prevent duplicate terminal sends on retries/restarts.
- [x] 3.5 Persist machine-readable terminal failure reason codes.

## 4. Observability and Verification

- [x] 4.1 Emit structured events for enqueue, dequeue, retry scheduled, retry exhausted, sent, and terminal failure.
- [x] 4.2 Add metrics for queue lag, active per-account workers, retry count, and terminal failure rates.
- [x] 4.3 Add alert thresholds/dashboards for abnormal retry storms and stuck `in-flight` attempts.
- [x] 4.4 Add integration tests for concurrent multi-account broadcasts and isolation behavior.
- [x] 4.5 Add integration tests for flood retry/backoff and terminal failure transitions.
