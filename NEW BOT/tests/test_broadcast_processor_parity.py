import pytest

from app.config import settings
from app.services.broadcast_processor_service import BroadcastProcessorService
from app.services.userbot_service import BroadcastExecutionResult


class DummyUserbot:
    def __init__(self, result: BroadcastExecutionResult):
        self.result = result
        self.calls = []

    async def broadcast_message(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class DummyQueue:
    def __init__(self):
        self.calls = []

    def continuation_delay_ms(self):
        return 500

    async def enqueue_send(self, **kwargs):
        self.calls.append(kwargs)
        return "job-1"


@pytest.mark.asyncio
async def test_non_worker_role_skips_processing(monkeypatch):
    monkeypatch.setattr(settings, "bot_role", "app", raising=False)
    service = BroadcastProcessorService(DummyUserbot(BroadcastExecutionResult(True, 0, [])), DummyQueue())
    result = await service.process({"userId": "1", "message": "x", "campaignId": "c", "queuedAt": "t"})
    assert result["success"] is True
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_continuation_is_enqueued_for_deferred_batch(monkeypatch):
    monkeypatch.setattr(settings, "bot_role", "worker", raising=False)
    result = BroadcastExecutionResult(
        success=False,
        count=1,
        errors=[],
        error=None,
        summary={"pending": 2, "inFlight": 0, "failed": 0, "sent": 1},
    )
    userbot = DummyUserbot(result)
    queue = DummyQueue()

    service = BroadcastProcessorService(userbot, queue)
    monkeypatch.setattr(service, "acquire_user_lock", lambda *args, **kwargs: _async_true())
    monkeypatch.setattr(service, "release_user_lock", lambda *args, **kwargs: _async_none())

    payload = {"userId": "10", "message": "hello", "campaignId": "cmp-1", "queuedAt": "2026-01-01T00:00:00Z"}
    out = await service.process(payload)

    assert out["success"] is True
    assert len(userbot.calls) == 1
    assert len(queue.calls) == 1
    assert queue.calls[0]["campaign_id"] == "cmp-1"
    assert queue.calls[0]["job_id"].startswith("bc-cont-cmp-1-10-")


@pytest.mark.asyncio
async def test_pending_only_result_is_not_failure(monkeypatch):
    monkeypatch.setattr(settings, "bot_role", "worker", raising=False)
    result = BroadcastExecutionResult(
        success=False,
        count=0,
        errors=[],
        error=None,
        summary={"pending": 3, "inFlight": 0, "failed": 0, "sent": 0, "nextDueInMs": 2000},
    )
    userbot = DummyUserbot(result)
    queue = DummyQueue()

    service = BroadcastProcessorService(userbot, queue)
    monkeypatch.setattr(service, "acquire_user_lock", lambda *args, **kwargs: _async_true())
    monkeypatch.setattr(service, "release_user_lock", lambda *args, **kwargs: _async_none())

    payload = {"userId": "10", "message": "hello", "campaignId": "cmp-1", "queuedAt": "2026-01-01T00:00:00Z"}
    out = await service.process(payload)

    assert out["success"] is True
    assert len(queue.calls) == 1


async def _async_true():
    return True


async def _async_none():
    return None
