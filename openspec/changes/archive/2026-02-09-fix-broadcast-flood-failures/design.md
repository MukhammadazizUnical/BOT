## Context

The current broadcast flow allows many concurrent send attempts when multiple users launch campaigns at once, which creates timing collisions and inconsistent state updates. Telegram flood/rate-limit responses are not treated as first-class retry signals, so the system can mark sends as failed before a terminal outcome is known. We need a design that keeps sender workloads isolated, enforces predictable throughput, and records delivery lifecycle transitions in a single source of truth.

## Goals / Non-Goals

**Goals:**

- Enforce per-account broadcast isolation so one sender's load does not degrade others.
- Introduce deterministic dispatch order with explicit concurrency and rate controls.
- Treat flood responses as retriable with bounded backoff based on platform hints.
- Persist attempt lifecycle states so status reflects actual terminal outcomes.
- Provide metrics/logs to diagnose queue lag, retry frequency, and failure causes.

**Non-Goals:**

- Redesigning campaign authoring UX or message template features.
- Guaranteeing exactly-once delivery across external transport failures.
- Replacing the existing queue/storage technology stack end-to-end.

## Decisions

1. Per-account queue partitioning
   - Decision: Partition broadcast jobs by sender/account key and process each partition with a small configurable worker pool.
   - Rationale: Prevents cross-account interference while still allowing global throughput.
   - Alternatives considered:
     - Single global queue with shared workers: simpler but causes starvation and noisy-neighbor effects.
     - Dedicated process per account: strong isolation but too costly operationally.

2. Stateful attempt lifecycle model
   - Decision: Store each recipient send attempt with explicit states (`pending`, `in-flight`, `sent`, `failed-terminal`) and transition timestamps.
   - Rationale: Eliminates ambiguous "failed" reports and supports restart-safe recovery.
   - Alternatives considered:
     - In-memory status only: fast but loses correctness on restarts.
     - Final-state-only persistence: insufficient for observability and retry logic.

3. Flood-aware retry policy
   - Decision: For flood/rate-limit errors, apply bounded retries using `retry_after` when provided, plus jitter and max-attempt caps.
   - Rationale: Aligns with Telegram limits, reduces false failures, and smooths retry spikes.
   - Alternatives considered:
     - Immediate fail on flood: simple but incorrect for transient limits.
     - Fixed delay retries: easier but ignores dynamic platform guidance.

4. Idempotency and de-duplication guard
   - Decision: Assign deterministic idempotency keys per campaign-recipient attempt to avoid duplicate terminal sends after worker restarts.
   - Rationale: Reduces duplicate delivery risk in distributed execution.
   - Alternatives considered:
     - No idempotency key: vulnerable to duplicate sends.
     - Global lock per campaign: safer but reduces parallelism too much.

5. Observability contract
   - Decision: Emit structured events/metrics for enqueue, dequeue, retry scheduled, retry exhausted, sent, and terminal failure.
   - Rationale: Enables accurate operational diagnosis and SLA tracking.
   - Alternatives considered:
     - Log-only text traces: insufficient for dashboards/alerts.

## Risks / Trade-offs

- [Higher system complexity] -> Mitigation: keep retry/state logic in a single send orchestrator module with clear interfaces and tests.
- [Longer delivery time under strict throttling] -> Mitigation: make limits configurable per account tier and expose queue ETA telemetry.
- [State drift between queue and DB] -> Mitigation: enforce state transitions atomically and reconcile stuck `in-flight` attempts with a recovery job.
- [Retry storms after platform outages] -> Mitigation: use capped exponential backoff with jitter and per-account retry concurrency limits.
