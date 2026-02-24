import pytest

import app.bot_runner as bot_runner


class _DummyUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _DummyMessage:
    pass


class _DummyCallback:
    def __init__(self, user_id: int, data: str):
        self.from_user = _DummyUser(user_id)
        self.data = data
        self.message = _DummyMessage()
        self.answer_calls = []

    async def answer(self, text: str, show_alert: bool = False):
        self.answer_calls.append((text, show_alert))


@pytest.mark.asyncio
async def test_add_all_groups_adds_missing_groups(monkeypatch):
    added = []

    async def fake_logged_in(_callback):
        return True

    async def fake_remote(_user_id):
        return [
            {"id": "g1", "title": "Group 1", "type": "supergroup", "access_hash": "a1"},
            {"id": "g2", "title": "Group 2", "type": "chat", "access_hash": None},
        ]

    class _G:
        def __init__(self, gid: str):
            self.id = gid

    async def fake_get_groups(_user_id, active_only=False):
        return [_G("g1")]

    async def fake_add_group(user_id, group_id, title, kind, access_hash):
        added.append((user_id, group_id, title, kind, access_hash))

    async def fake_render(_message, _user_id, _page, is_edit=False):
        return None

    monkeypatch.setattr(bot_runner, "ensure_logged_in", fake_logged_in)
    monkeypatch.setattr(bot_runner.userbot_service, "get_remote_groups", fake_remote)
    monkeypatch.setattr(bot_runner.group_service, "get_groups", fake_get_groups)
    monkeypatch.setattr(bot_runner.group_service, "add_group", fake_add_group)
    monkeypatch.setattr(bot_runner, "render_add_group_page", fake_render)

    callback = _DummyCallback(100, "add_all_groups_0")
    await bot_runner.on_add_all_groups(callback)

    assert len(added) == 2
    assert any(call[1] == "g2" for call in added)
    assert callback.answer_calls[-1][0].startswith("✅ 1 ta guruh qo'shildi")


@pytest.mark.asyncio
async def test_add_all_groups_handles_empty_remote(monkeypatch):
    async def fake_logged_in(_callback):
        return True

    async def fake_remote(_user_id):
        return []

    async def fake_render(_message, _user_id, _page, is_edit=False):
        return None

    monkeypatch.setattr(bot_runner, "ensure_logged_in", fake_logged_in)
    monkeypatch.setattr(bot_runner.userbot_service, "get_remote_groups", fake_remote)
    monkeypatch.setattr(bot_runner, "render_add_group_page", fake_render)

    callback = _DummyCallback(100, "add_all_groups_2")
    await bot_runner.on_add_all_groups(callback)

    assert callback.answer_calls[-1][0] == "Import uchun guruh topilmadi"
    assert callback.answer_calls[-1][1] is True
