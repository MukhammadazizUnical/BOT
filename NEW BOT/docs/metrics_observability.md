# Metrics and Observability

This bot exposes two metrics endpoints from the `app` service:

- `GET /metrics` -> JSON snapshot
- `GET /metrics/prometheus` -> Prometheus text format

Both endpoints return **global** metrics aggregated through Redis, so worker-produced metrics are visible from `app`.

## One-command observability stack

Run base stack + observability overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d --build
```

Endpoints after startup:

- Grafana: `http://localhost:3001` (default login `admin` / `admin`)
- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`
- App metrics JSON: `http://localhost:3011/metrics`
- App metrics Prometheus: `http://localhost:3011/metrics/prometheus`

The dashboard `SEND_BOT Broadcast Observability` is provisioned automatically from `docs/grafana_broadcast_observability_dashboard.json`.

## Built-in Prometheus alerts

The overlay also loads `observability/prometheus/alerts.yml` with these default rules:

- `SendBotHighProcessorLag`: lag above 120s for 5 minutes.
- `SendBotFailureRatioHigh`: failed outcome ratio above 20% for 10 minutes.
- `SendBotLockContentionHigh`: sustained lock contention rate.
- `SendBotNoProcessingActivity`: no processing increments for 15 minutes.

You can tune thresholds in `observability/prometheus/alerts.yml` based on your traffic profile.

Alerts are routed through Alertmanager and sent to `app` webhook endpoint:

- `POST /alerts/prometheus`

By default, app does NOT forward alert messages to Telegram (`ALERT_WEBHOOK_FORWARD_ENABLED=false`).
If you want forwarding, set `ALERT_WEBHOOK_FORWARD_ENABLED=true` and configure `OWNER_USER_ID` + `TG_BOT_TOKEN`.

To control Telegram alert pacing:

- Alertmanager `group_interval` and `repeat_interval` are set to `5m` in `observability/alertmanager/alertmanager.yml`.
- App-side cooldown suppresses duplicate `firing` notifications for the same alert signature using Redis.
- Cooldown window is controlled by `ALERT_WEBHOOK_COOLDOWN_SECONDS` (default `300`).

### Optional webhook authentication

Set `ALERT_WEBHOOK_TOKEN` in `.env` to require Bearer auth on `/alerts/prometheus`.

- App validates `Authorization: Bearer <ALERT_WEBHOOK_TOKEN>`.
- If you enable this, update `observability/alertmanager/alertmanager.yml` receiver to send the same Bearer token.

## Import Grafana dashboard

1. Open Grafana -> Dashboards -> Import.
2. Upload `docs/grafana_broadcast_observability_dashboard.json`.
3. Select your Prometheus datasource when prompted.
4. Save dashboard.

If you use the overlay compose file, manual import is optional because provisioning loads the dashboard automatically.

## Prometheus scrape config example

```yaml
scrape_configs:
  - job_name: send-bot-app
    metrics_path: /metrics/prometheus
    static_configs:
      - targets: ["app:3010"]
```

If Prometheus runs outside Docker, use your published host port (for this project default is `localhost:3011`).

## Key metrics

- `processor_result_total{service="processor"}`: total processed runs.
- `processor_result_by_outcome{service="processor", outcome="..."}`: outcome split (`sent`, `deferred`, `failed`, etc).
- `processor_continuation_enqueued{service="processor", reason="..."}`: continuation scheduling reasons.
- `processor_lock_busy{service="processor"}`: lock contention signals.
- `processor_last_lag_ms{service="processor"}`: last observed queue lag.
- `worker_startup_count{service="worker"}`: worker restart counter.
- `alertmanager_webhook_received{service="app"}`: webhook notifications received by app.
- `alertmanager_webhook_sent{service="app"}`: notifications successfully forwarded to Telegram.

## Quick validation

```bash
curl http://localhost:3011/metrics
curl http://localhost:3011/metrics/prometheus
```
