import pytest

import app.services.userbot_service as us
from app.services.userbot_service import UserbotService


class _FakeClientOk:
    def __init__(self, *args, **kwargs):
        self.sign_in_calls = []

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def sign_in(self, phone, phone_code_hash, code):
        self.sign_in_calls.append((phone, phone_code_hash, code))

        class _Me:
            first_name = "Test"
            last_name = None
            username = "t"

        return _Me()

    async def export_session_string(self):
        return "session-string"


class _FakeClientPwd:
    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def sign_in(self, phone, phone_code_hash, code):
        raise us.SessionPasswordNeeded()


@pytest.mark.asyncio
async def test_complete_login_missing_temp_session():
    svc = UserbotService()
    res = await svc.complete_login(100, "+998901234567", "1 2 3 4 5")
    assert res["success"] is False
    assert "not found" in res["error"].lower()


@pytest.mark.asyncio
async def test_complete_login_normalizes_spaced_code(monkeypatch):
    fake = _FakeClientOk()
    monkeypatch.setattr(us, "Client", lambda *a, **k: fake)

    svc = UserbotService()
    svc.login_temp[101] = {
        "phone": "+998901234567",
        "phone_code_hash": "h",
        "session_name": "login_101",
    }

    saved = {}

    async def _save(user_id, phone, me, session_string):
        saved["ok"] = (user_id, phone, session_string)

    monkeypatch.setattr(svc, "_save_telegram_account", _save)

    res = await svc.complete_login(101, "+998901234567", "1 2 3 4 5")
    assert res["success"] is True
    assert fake.sign_in_calls[0][2] == "12345"
    assert saved["ok"][1] == "+998901234567"


@pytest.mark.asyncio
async def test_complete_login_requires_password(monkeypatch):
    monkeypatch.setattr(us, "Client", lambda *a, **k: _FakeClientPwd())

    svc = UserbotService()
    svc.login_temp[102] = {
        "phone": "+998901234567",
        "phone_code_hash": "h",
        "session_name": "login_102",
    }

    res = await svc.complete_login(102, "+998901234567", "12345")
    assert res["success"] is False
    assert res.get("requiresPassword") is True
