# Low Worker Broadcast Tuning

## Recommended Defaults

- `SCHEDULER_EARLY_FACTOR=1.0`
- `SCHEDULER_JITTER_MAX_MS=0`
- `BROADCAST_ATTEMPTS_PER_JOB=20`
- `BROADCAST_PER_ACCOUNT_CONCURRENCY=1`
- `BROADCAST_CONTINUATION_BASE_DELAY_MS=1500`
- `BROADCAST_CONTINUATION_JITTER_MS=0`
- `TELEGRAM_PER_ACCOUNT_MPM=20`
- `TELEGRAM_PER_ACCOUNT_MIN_DELAY_MS=3000`

## Why These Defaults

- `SCHEDULER_EARLY_FACTOR=1.0` prevents early runs before the configured interval boundary.
- Lower continuation jitter helps predictable cadence for low worker pools.
- Bounded attempts per job reduces worker starvation from one heavy campaign.
- Per-account concurrency `1` keeps Telegram flood pressure manageable.

## Staged Rollout Plan (1 -> 2 -> 4 workers)

1. Start with one worker and observe 15-30 minutes.
2. Increase to two workers and compare lag/error outcomes.
3. Increase to four workers only if lag/failure metrics remain stable.

## Acceptance Checks

- p95 interval lag for 5-minute campaigns remains under agreed SLO.
- No sustained spikes in `no-account` outcomes.
- `provider-constrained-delay` is explainable by Telegram wait errors.
- No recurring per-user lock contention loops for active campaigns.
