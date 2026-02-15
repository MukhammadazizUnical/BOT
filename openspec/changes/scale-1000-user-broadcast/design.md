## Context

The broadcast runtime currently combines scheduler ticks, ARQ queue jobs, and per-user attempt state in PostgreSQL. Under low worker counts and high active-user volume, small logic mistakes (early scheduling, duplicate continuation enqueue, stale checks tied to config metadata) can produce timing drift, wasted jobs, and visible inconsistency in send cadence. The required outcome is stable interval execution for large concurrency (target around 1000 active broadcasters) while preserving safety for Telegram flood control and account availability constraints.

Primary constraints:
- Workers are intentionally limited (1-4) in some deployments.
- Telegram-side limits (flood wait, slow mode) can delay specific targets.
- Redis queue and DB should not be saturated by non-actionable jobs.
- Existing NodeJS-parity behavior should be preserved where compatible with interval guarantees.

## Goals / Non-Goals

**Goals:**
- Guarantee no campaign run is scheduled earlier than configured interval.
- Improve fairness so users with valid accounts and due campaigns are served first, even with few workers.
- Reduce queue waste (stale/no-account/non-actionable jobs) without blocking valid progress.
- Make runtime outcomes observable with clear reasons for skip/defer/failure.
- Keep retry behavior compatible with Telegram rate-limit semantics.

**Non-Goals:**
- Guarantee exact wall-clock send time per target group when Telegram enforces flood/slow-mode limits.
- Re-architecting away from ARQ/Redis/PostgreSQL in this change.
- Building a full multi-tenant priority scheduler with new infrastructure.
- Changing user-facing bot flows unrelated to broadcast runtime correctness.

## Decisions

1) Interval gate is attempt-state driven, not config-update driven.
- Decision: enforce interval progression by `BroadcastAttempt.sent_at`/`next_attempt_at` and campaign interval windows, not by `BroadcastConfig.updated_at` freshness checks.
- Rationale: config updates are broad metadata and can change for reasons unrelated to message validity; tying staleness to config timestamp causes false skips.
- Alternative considered: keep `queued_at < config.updated_at` and patch selected fields. Rejected because it is fragile and repeatedly caused valid jobs to be dropped.

2) Scheduler enqueues only actionable campaigns.
- Decision: due selection must require at least one available Telegram account (active and not currently flood-blocked) and an active campaign message/interval.
- Rationale: prevents worker time from being consumed by immediate "no active account" terminal responses.
- Alternative considered: enqueue all due campaigns then fail in processor. Rejected because it creates avoidable queue churn under low worker counts.

3) Continuation is state-based and bounded.
- Decision: enqueue continuation only when processor summary indicates pending/in-flight work and no terminal error; continuation delay respects `nextDueInMs` and minimum continuation base delay.
- Rationale: keeps campaigns progressing without flooding queue with redundant follow-ups.
- Alternative considered: always enqueue continuation on non-success. Rejected due to queue storms.

4) Fairness over raw throughput for low-worker mode.
- Decision: preserve per-user lock and rely on short scheduler ticks with controlled attempts-per-job so one heavy user does not monopolize workers.
- Rationale: stable cross-user cadence is more important than maximum per-user burst throughput in production.
- Alternative considered: large per-job attempt budgets. Rejected because long-running jobs starve other users when workers are few.

5) Failure contract is explicit.
- Decision: processor result is success unless a real send failure condition exists (`error` present or failed-attempt count > 0). Pending-only states are not hard failure.
- Rationale: aligns operational meaning with user expectation (only unsent/failing cases should be marked failed).
- Alternative considered: `success = count > 0`. Rejected because it marks healthy deferred runs as failures.

6) Observability first-class for interval SLO.
- Decision: emit structured outcome categories (`sent`, `deferred`, `inactive-campaign`, `no-account`, `stale-message`, `lock-busy`) and log queue lag (`scheduled_at` vs execution start).
- Rationale: production tuning for 1000-user load requires direct visibility into cause breakdown and lag trends.
- Alternative considered: rely on existing free-form logs. Rejected as insufficient for diagnosing drift.

## Risks / Trade-offs

- [Low worker count increases tail latency for large campaigns] -> Mitigation: keep attempts-per-job bounded, prioritize actionable campaigns, and document tuning thresholds.
- [Telegram flood waits can exceed configured interval] -> Mitigation: treat provider wait as hard lower bound; report as provider-constrained delay, not scheduler error.
- [Over-filtering due campaigns may delay recovery after transient account state changes] -> Mitigation: re-evaluate availability each scheduler tick and avoid long suppression windows.
- [Reduced dedupe can increase queue volume if continuation logic regresses] -> Mitigation: continuation guarded by actionable summary + lag metrics + skip-reason counters.
- [Behavior differences vs legacy Node implementation in edge cases] -> Mitigation: capture parity-critical paths in tests and explicitly document intentional differences.

## Migration Plan

1. Add and verify scheduler actionable-campaign filters and strict interval gate behavior in tests.
2. Update processor stale/failure semantics and continuation guard conditions.
3. Tune default env values for low-worker reliability (`SCHEDULER_EARLY_FACTOR=1.0`, bounded attempts-per-job, low jitter by default).
4. Deploy to staging with 1-2 workers and synthetic multi-user load; validate interval lag percentiles and skip-reason distribution.
5. Roll out to production gradually (2 -> 4 workers), monitor lag and no-account churn.
6. Rollback strategy: revert runtime service changes and env overrides to previous release tag if lag/failure SLO degrades.

## Open Questions

- What exact interval SLO is required (for example, p95 lag <= 30s for 5-minute campaigns under 1000 active users)?
- Should users with repeated `no-account` outcomes be auto-paused until account reconnect, and after how many consecutive runs?
- Do we need explicit weighted fairness (per-user quota) beyond current lock + bounded attempt model?
