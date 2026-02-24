import pytest

import app.main as main_mod


class _DummyRequest:
    def __init__(self, payload: dict, headers: dict | None = None):
        self._payload = payload
        self.headers = headers or {}

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_alert_webhook_skips_when_no_owner_chat(monkeypatch):
    async def fake_inc(*args, **kwargs):
        return None

    async def fake_send(chat_id: str, text: str):
        return True

    monkeypatch.setattr(main_mod, "inc_metric", fake_inc)
    monkeypatch.setattr(main_mod, "_send_bot_text", fake_send)
    monkeypatch.setattr(main_mod, "_resolve_alert_chat_id", lambda: None)
    monkeypatch.setattr(main_mod.settings, "alert_webhook_token", "")
    monkeypatch.setattr(main_mod.settings, "alert_webhook_forward_enabled", True)

    req = _DummyRequest({"status": "firing", "alerts": []})
    result = await main_mod.prometheus_alert_webhook(req)
    assert result["ok"] is True
    assert result["forwarded"] is False
    assert result["reason"] == "no_owner_chat"


@pytest.mark.asyncio
async def test_alert_webhook_forwards_to_owner(monkeypatch):
    async def fake_inc(*args, **kwargs):
        return None

    called = {"sent": False, "chat": ""}

    async def fake_send(chat_id: str, text: str):
        called["sent"] = True
        called["chat"] = chat_id
        return "PROMETHEUS ALERT" in text

    monkeypatch.setattr(main_mod, "inc_metric", fake_inc)
    monkeypatch.setattr(main_mod, "_send_bot_text", fake_send)
    monkeypatch.setattr(main_mod, "_resolve_alert_chat_id", lambda: "8553443423")

    async def fake_should_send(_payload: dict):
        return True

    monkeypatch.setattr(main_mod, "_should_send_alert", fake_should_send)
    monkeypatch.setattr(main_mod.settings, "alert_webhook_token", "")
    monkeypatch.setattr(main_mod.settings, "alert_webhook_forward_enabled", True)

    req = _DummyRequest(
        {
            "status": "firing",
            "alerts": [
                {"status": "firing", "labels": {"alertname": "SendBotHighProcessorLag"}}
            ],
        }
    )
    result = await main_mod.prometheus_alert_webhook(req)
    assert result["ok"] is True
    assert result["forwarded"] is True
    assert called["sent"] is True
    assert called["chat"] == "8553443423"


@pytest.mark.asyncio
async def test_alert_webhook_skips_on_cooldown(monkeypatch):
    async def fake_inc(*args, **kwargs):
        return None

    called = {"sent": False}

    async def fake_send(chat_id: str, text: str):
        called["sent"] = True
        return True

    async def fake_should_send(payload: dict):
        return False

    monkeypatch.setattr(main_mod, "inc_metric", fake_inc)
    monkeypatch.setattr(main_mod, "_send_bot_text", fake_send)
    monkeypatch.setattr(main_mod, "_should_send_alert", fake_should_send)
    monkeypatch.setattr(main_mod, "_resolve_alert_chat_id", lambda: "8553443423")
    monkeypatch.setattr(main_mod.settings, "alert_webhook_token", "")
    monkeypatch.setattr(main_mod.settings, "alert_webhook_forward_enabled", True)

    req = _DummyRequest({"status": "firing", "alerts": [{"status": "firing", "labels": {"alertname": "SendBotHighProcessorLag"}}]})
    result = await main_mod.prometheus_alert_webhook(req)

    assert result["ok"] is True
    assert result["forwarded"] is False
    assert result["reason"] == "cooldown"
    assert called["sent"] is False


@pytest.mark.asyncio
async def test_alert_webhook_skips_resolved_notifications(monkeypatch):
    async def fake_inc(*args, **kwargs):
        return None

    called = {"sent": False}

    async def fake_send(chat_id: str, text: str):
        called["sent"] = True
        return True

    monkeypatch.setattr(main_mod, "inc_metric", fake_inc)
    monkeypatch.setattr(main_mod, "_send_bot_text", fake_send)
    monkeypatch.setattr(main_mod, "_resolve_alert_chat_id", lambda: "8553443423")
    monkeypatch.setattr(main_mod.settings, "alert_webhook_token", "")
    monkeypatch.setattr(main_mod.settings, "alert_webhook_forward_enabled", True)

    req = _DummyRequest({"status": "resolved", "alerts": [{"status": "resolved", "labels": {"alertname": "SendBotHighProcessorLag"}}]})
    result = await main_mod.prometheus_alert_webhook(req)

    assert result["ok"] is True
    assert result["forwarded"] is False
    assert result["reason"] == "resolved"
    assert called["sent"] is False


@pytest.mark.asyncio
async def test_alert_webhook_rejects_invalid_token(monkeypatch):
    async def fake_inc(*args, **kwargs):
        return None

    monkeypatch.setattr(main_mod, "inc_metric", fake_inc)
    monkeypatch.setattr(main_mod.settings, "alert_webhook_token", "secret-token")
    monkeypatch.setattr(main_mod.settings, "alert_webhook_forward_enabled", True)

    req = _DummyRequest({"status": "firing", "alerts": []}, headers={"authorization": "Bearer wrong"})

    with pytest.raises(main_mod.HTTPException) as exc:
        await main_mod.prometheus_alert_webhook(req)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_alert_webhook_is_disabled_by_default(monkeypatch):
    async def fake_inc(*args, **kwargs):
        return None

    async def fake_send(chat_id: str, text: str):
        return True

    monkeypatch.setattr(main_mod, "inc_metric", fake_inc)
    monkeypatch.setattr(main_mod, "_send_bot_text", fake_send)
    monkeypatch.setattr(main_mod.settings, "alert_webhook_token", "")
    monkeypatch.setattr(main_mod.settings, "alert_webhook_forward_enabled", False)

    req = _DummyRequest({"status": "firing", "alerts": [{"status": "firing", "labels": {"alertname": "X"}}]})
    result = await main_mod.prometheus_alert_webhook(req)
    assert result["ok"] is True
    assert result["forwarded"] is False
    assert result["reason"] == "disabled"
