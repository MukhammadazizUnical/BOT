# Staged Rollout Results (1 -> 2 -> 4 workers)

## Run Commands

```bash
docker compose up -d --build app worker bot --scale worker=1
docker compose logs --since=30m worker > worker-1.log
python tools/analyze_broadcast_logs.py worker-1.log

docker compose up -d --build app worker bot --scale worker=2
docker compose logs --since=30m worker > worker-2.log
python tools/analyze_broadcast_logs.py worker-2.log

docker compose up -d --build app worker bot --scale worker=4
docker compose logs --since=30m worker > worker-4.log
python tools/analyze_broadcast_logs.py worker-4.log
```

## Acceptance Targets

- p95 lag for 5-minute campaigns: `<target-ms>`
- No sustained growth in `no-account` outcomes
- `provider-constrained-delay` appears only when flood/slowmode conditions exist

## Results Table

| Workers | Processed Jobs | Lag p50 (ms) | Lag p95 (ms) | Lag max (ms) | sent | deferred | no-account | lock-busy | provider-constrained-delay |
| ------- | -------------- | ------------ | ------------ | ------------ | ---- | -------- | ---------- | --------- | -------------------------- |
| 1       |                |              |              |              |      |          |            |           |                            |
| 2       |                |              |              |              |      |          |            |           |                            |
| 4       |                |              |              |              |      |          |            |           |                            |

## Notes

- Observed issues:
- Mitigations applied:
- Final recommendation:
