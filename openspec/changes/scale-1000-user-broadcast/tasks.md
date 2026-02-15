## 1. Interval Correctness Core

- [x] 1.1 Remove config-timestamp-based stale rejection from processor and keep stale checks message/campaign-state based
- [x] 1.2 Enforce strict campaign lower-bound interval using attempt lifecycle fields (`sent_at`, `next_attempt_at`) for cycle eligibility
- [x] 1.3 Ensure scheduler run bookkeeping updates only for actually enqueued actionable runs
- [x] 1.4 Add tests for 5-minute interval behavior proving no early execution before 300 seconds

## 2. Actionable Scheduling and Fairness

- [x] 2.1 Filter due campaigns to enqueue only when at least one account is active and currently runnable (not flood-blocked)
- [x] 2.2 Keep per-user lock semantics and validate no parallel processing for same user across concurrent jobs
- [x] 2.3 Bound per-job attempt budget and verify heavy campaigns yield worker time under low worker counts
- [x] 2.4 Add fairness regression tests for multi-user due windows with 1-2 workers

## 3. Delivery State and Retry Semantics

- [x] 3.1 Update attempt recycle rules so `sent` and `failed-terminal` become eligible only in next interval window
- [x] 3.2 Preserve explicit terminal reason codes and retry counters across retriable and terminal paths
- [x] 3.3 Enforce provider wait lower bound (`retry_after` or slow-mode default) before scheduling next retry
- [x] 3.4 Add unit/integration tests for flood-wait, slow-mode, retry exhaustion, and new-cycle recovery

## 4. Queue Pressure and Continuation Control

- [x] 4.1 Guard continuation enqueue to only actionable deferred states (pending/in-flight with no terminal error)
- [x] 4.2 Prevent no-account campaigns from repeatedly consuming queue slots during scheduler ticks
- [ ] 4.3 Validate queue lag and throughput behavior under synthetic 1000-user load with low workers
- [x] 4.4 Add regression test covering duplicate/non-actionable job suppression without blocking valid sends

## 5. Observability, Rollout, and Validation

- [x] 5.1 Emit structured runtime outcomes (`sent`, `deferred`, `inactive-campaign`, `no-account`, `lock-busy`, `provider-constrained-delay`)
- [x] 5.2 Add lag telemetry fields (`scheduled_at`, `started_at`, `lag_ms`) for each campaign run
- [x] 5.3 Define and document production tuning defaults for low-worker deployment (`SCHEDULER_EARLY_FACTOR`, attempts-per-job, jitter)
- [ ] 5.4 Execute staged rollout checks (1->2->4 workers) and record acceptance criteria results for interval SLO
