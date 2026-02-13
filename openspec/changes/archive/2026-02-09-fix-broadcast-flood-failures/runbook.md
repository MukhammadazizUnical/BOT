## Broadcast Observability Runbook

### Structured events

- `enqueue`: broadcast campaign entered queue (`userId`, `campaignId`, `totalTargets`, `queueLagMs`)
- `dequeue`: attempt claimed by worker lane (`attemptId`, `accountId`, `sequence`)
- `sent`: attempt delivered successfully
- `retry_scheduled`: retriable error scheduled for next attempt
- `retry_exhausted`: attempt reached retry budget
- `terminal_failure`: terminal outcome with `reasonCode`
- `metrics_snapshot`: end-of-cycle counters (`pending`, `inFlight`, cumulative metrics)
- `recovered_stuck_in_flight`: stale in-flight attempts reset after restart

### Alert thresholds (env)

- `BROADCAST_RETRY_STORM_THRESHOLD` (default `50`)
- `BROADCAST_STUCK_INFLIGHT_THRESHOLD` (default `10`)
- `BROADCAST_QUEUE_LAG_ALERT_MS` (default `120000`)
- `BROADCAST_INFLIGHT_STUCK_MS` (default `300000`)

### Suggested dashboard panels

- Queue lag (`queueLagMs`) by campaign and user
- In-flight attempts count over time
- Retry scheduled and retry exhausted rates
- Terminal failures by `reasonCode`
- Sent vs failed-terminal ratio per campaign
