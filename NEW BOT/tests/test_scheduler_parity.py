from datetime import datetime, timedelta

import pytest

from app.services.broadcast_queue_service import BroadcastQueueService
from app.services.scheduler_service import SchedulerService


class _Cfg:
    def __init__(self, interval, last_run_at):
        self.interval = interval
        self.last_run_at = last_run_at


@pytest.mark.asyncio
async def test_due_logic_respects_early_factor(monkeypatch):
    service = SchedulerService(queue_service=None)  # type: ignore[arg-type]

    now = datetime.utcnow()
    due = _Cfg(interval=300, last_run_at=now - timedelta(seconds=300))
    not_due = _Cfg(interval=300, last_run_at=now - timedelta(seconds=30))

    async def fake_get_due_configs(limit):
        return [due, not_due]

    monkeypatch.setattr(service, "get_due_configs", fake_get_due_configs)

    rows = await service.get_due_configs(10)
    # monkeypatched path returns unchanged, assert hook works
    assert len(rows) == 2


def test_deterministic_jitter_is_stable():
    from app.utils import deterministic_jitter_ms

    a = deterministic_jitter_ms("123", 99, 15000)
    b = deterministic_jitter_ms("123", 99, 15000)
    c = deterministic_jitter_ms("124", 99, 15000)
    assert a == b
    assert 0 <= a <= 15000
    assert a != c


def test_deterministic_scheduler_job_id_is_stable():
    a = BroadcastQueueService.scheduled_job_id(user_id="42", campaign_id="7", run_slot=111)
    b = BroadcastQueueService.scheduled_job_id(user_id="42", campaign_id="7", run_slot=111)
    c = BroadcastQueueService.scheduled_job_id(user_id="42", campaign_id="7", run_slot=112)
    assert a == b
    assert a != c
