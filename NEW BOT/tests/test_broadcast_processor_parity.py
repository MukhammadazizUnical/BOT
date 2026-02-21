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
    service = BroadcastProcessorService(
        DummyUserbot(BroadcastExecutionResult(True, 0, [])), DummyQueue()
    )
    result = await service.process(
        {"userId": "1", "message": "x", "campaignId": "c", "queuedAt": "t"}
    )
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
    monkeypatch.setattr(
        service, "acquire_user_lock", lambda *args, **kwargs: _async_true()
    )
    monkeypatch.setattr(
        service, "release_user_lock", lambda *args, **kwargs: _async_none()
    )

    payload = {
        "userId": "10",
        "message": "hello",
        "campaignId": "cmp-1",
        "queuedAt": "2026-01-01T00:00:00Z",
    }
    out = await service.process(payload)

    assert out["success"] is True
    assert len(userbot.calls) == 1
    assert len(queue.calls) == 1
    assert queue.calls[0]["campaign_id"] == "cmp-1"
    assert out["continuationEnqueued"] is True
    assert out["continuationDelayMs"] == 500
    assert out["continuationReason"] == "default-deferred"


@pytest.mark.asyncio
async def test_pending_only_result_is_not_failure(monkeypatch):
    monkeypatch.setattr(settings, "bot_role", "worker", raising=False)
    result = BroadcastExecutionResult(
        success=False,
        count=0,
        errors=[],
        error=None,
        summary={
            "pending": 3,
            "inFlight": 0,
            "failed": 0,
            "sent": 0,
            "nextDueInMs": 2000,
        },
    )
    userbot = DummyUserbot(result)
    queue = DummyQueue()

    service = BroadcastProcessorService(userbot, queue)
    monkeypatch.setattr(
        service, "acquire_user_lock", lambda *args, **kwargs: _async_true()
    )
    monkeypatch.setattr(
        service, "release_user_lock", lambda *args, **kwargs: _async_none()
    )

    payload = {
        "userId": "10",
        "message": "hello",
        "campaignId": "cmp-1",
        "queuedAt": "2026-01-01T00:00:00Z",
    }
    out = await service.process(payload)

    assert out["success"] is True
    assert out["outcome"] == "deferred"
    assert out["lagMs"] >= 0
    assert "scheduledAt" in out
    assert "startedAt" in out
    assert len(queue.calls) == 1
    assert out["continuationEnqueued"] is True
    assert out["continuationDelayMs"] == 2000
    assert out["continuationReason"] == "default-deferred"


@pytest.mark.asyncio
async def test_lock_busy_returns_non_failure_outcome(monkeypatch):
    monkeypatch.setattr(settings, "bot_role", "worker", raising=False)
    userbot = DummyUserbot(BroadcastExecutionResult(True, 0, []))
    queue = DummyQueue()
    service = BroadcastProcessorService(userbot, queue)
    monkeypatch.setattr(
        service, "acquire_user_lock", lambda *args, **kwargs: _async_false()
    )

    out = await service.process(
        {
            "userId": "10",
            "message": "hello",
            "campaignId": "cmp-1",
            "queuedAt": "2026-01-01T00:00:00Z",
        }
    )

    assert out["success"] is True
    assert out["error"] == "user-lock-busy"
    assert out["outcome"] == "lock-busy"
    assert len(userbot.calls) == 0


@pytest.mark.asyncio
async def test_no_account_is_structured_outcome(monkeypatch):
    monkeypatch.setattr(settings, "bot_role", "worker", raising=False)
    result = BroadcastExecutionResult(
        False,
        0,
        [],
        error="Faol Telegram akkaunt topilmadi",
        summary={"failed": 0, "pending": 0, "inFlight": 0},
    )
    userbot = DummyUserbot(result)
    queue = DummyQueue()
    service = BroadcastProcessorService(userbot, queue)
    monkeypatch.setattr(
        service, "acquire_user_lock", lambda *args, **kwargs: _async_true()
    )
    monkeypatch.setattr(
        service, "release_user_lock", lambda *args, **kwargs: _async_none()
    )

    out = await service.process(
        {
            "userId": "10",
            "message": "hello",
            "campaignId": "cmp-1",
            "queuedAt": "2026-01-01T00:00:00Z",
        }
    )

    assert out["success"] is False
    assert out["outcome"] == "no-account"
    assert len(queue.calls) == 0


@pytest.mark.asyncio
async def test_partial_delivery_with_some_failed_is_not_hard_failure(monkeypatch):
    monkeypatch.setattr(settings, "bot_role", "worker", raising=False)
    result = BroadcastExecutionResult(
        success=False,
        count=5,
        errors=[],
        error=None,
        summary={"failed": 3, "pending": 0, "inFlight": 0, "sent": 5},
    )
    userbot = DummyUserbot(result)
    queue = DummyQueue()
    service = BroadcastProcessorService(userbot, queue)
    monkeypatch.setattr(
        service, "acquire_user_lock", lambda *args, **kwargs: _async_true()
    )
    monkeypatch.setattr(
        service, "release_user_lock", lambda *args, **kwargs: _async_none()
    )

    out = await service.process(
        {
            "userId": "10",
            "message": "hello",
            "campaignId": "cmp-1",
            "queuedAt": "2026-01-01T00:00:00Z",
        }
    )

    assert out["success"] is True
    assert out["count"] == 5


@pytest.mark.asyncio
async def test_continuation_uses_exact_due_when_provider_constrained(monkeypatch):
    monkeypatch.setattr(settings, "bot_role", "worker", raising=False)
    result = BroadcastExecutionResult(
        success=False,
        count=7,
        errors=[],
        error=None,
        summary={
            "failed": 1,
            "pending": 1,
            "inFlight": 0,
            "sent": 7,
            "providerConstrainedDelay": True,
            "nextDueInMs": 180000,
        },
    )
    userbot = DummyUserbot(result)
    queue = DummyQueue()
    service = BroadcastProcessorService(userbot, queue)
    monkeypatch.setattr(
        service, "acquire_user_lock", lambda *args, **kwargs: _async_true()
    )
    monkeypatch.setattr(
        service, "release_user_lock", lambda *args, **kwargs: _async_none()
    )

    out = await service.process(
        {
            "userId": "10",
            "message": "hello",
            "campaignId": "cmp-1",
            "queuedAt": "2026-01-01T00:00:00Z",
        }
    )

    assert out["success"] is True
    assert len(queue.calls) == 1
    assert queue.calls[0]["delay_ms"] == 180000
    assert out["continuationEnqueued"] is True
    assert out["continuationDelayMs"] == 180000
    assert out["continuationReason"] == "exact-next-due"


@pytest.mark.asyncio
async def test_provider_constrained_ready_pending_uses_fast_continuation(monkeypatch):
    monkeypatch.setattr(settings, "bot_role", "worker", raising=False)
    result = BroadcastExecutionResult(
        success=False,
        count=2,
        errors=[],
        error=None,
        summary={
            "failed": 0,
            "pending": 3,
            "inFlight": 0,
            "sent": 2,
            "providerConstrainedDelay": True,
            "readyPendingCount": 1,
            "nextDueInMs": 240000,
        },
    )
    userbot = DummyUserbot(result)
    queue = DummyQueue()
    service = BroadcastProcessorService(userbot, queue)
    monkeypatch.setattr(
        service, "acquire_user_lock", lambda *args, **kwargs: _async_true()
    )
    monkeypatch.setattr(
        service, "release_user_lock", lambda *args, **kwargs: _async_none()
    )

    out = await service.process(
        {
            "userId": "10",
            "message": "hello",
            "campaignId": "cmp-1",
            "queuedAt": "2026-01-01T00:00:00Z",
        }
    )

    assert out["success"] is True
    assert len(queue.calls) == 1
    assert queue.calls[0]["delay_ms"] == 500
    assert out["continuationEnqueued"] is True
    assert out["continuationDelayMs"] == 500
    assert out["continuationReason"] == "ready-pending-fast"


async def _async_true():
    return True


async def _async_none():
    return None


async def _async_false():
    return False
