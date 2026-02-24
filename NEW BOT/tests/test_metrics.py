import pytest
from fastapi.responses import PlainTextResponse

import app.main as main_mod


@pytest.mark.asyncio
async def test_metrics_returns_snapshot(monkeypatch):
    async def fake_snapshot():
        return {
            "counters": {"worker.job.received": 3},
            "gauges": {"processor.last_lag_ms": 120},
        }

    monkeypatch.setattr(main_mod, "global_snapshot", fake_snapshot)

    result = await main_mod.metrics()
    assert result["ok"] is True
    assert "role" in result
    assert result["counters"]["worker.job.received"] == 3
    assert result["gauges"]["processor.last_lag_ms"] == 120


@pytest.mark.asyncio
async def test_metrics_prometheus_returns_text(monkeypatch):
    async def fake_prom_text():
        return "# TYPE worker_job_received counter\nworker_job_received 3\n"

    monkeypatch.setattr(main_mod, "global_prometheus_text", fake_prom_text)

    response = await main_mod.metrics_prometheus()
    assert isinstance(response, PlainTextResponse)
    body = response.body.decode("utf-8")
    assert "worker_job_received 3" in body
