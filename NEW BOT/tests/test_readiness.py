import pytest
from fastapi import HTTPException

import app.main as main_mod


@pytest.mark.asyncio
async def test_ready_returns_ok_when_db_and_redis_are_available(monkeypatch):
    async def fake_db_ready():
        return True

    async def fake_redis_ready():
        return True

    monkeypatch.setattr(main_mod, "_database_ready", fake_db_ready)
    monkeypatch.setattr(main_mod, "_redis_ready", fake_redis_ready)

    result = await main_mod.ready()
    assert result.ok is True
    assert result.database is True
    assert result.redis is True


@pytest.mark.asyncio
async def test_ready_returns_503_when_redis_unavailable(monkeypatch):
    async def fake_db_ready():
        return True

    async def fake_redis_ready():
        raise RuntimeError("redis down")

    monkeypatch.setattr(main_mod, "_database_ready", fake_db_ready)
    monkeypatch.setattr(main_mod, "_redis_ready", fake_redis_ready)

    with pytest.raises(HTTPException) as exc:
        await main_mod.ready()

    assert exc.value.status_code == 503
    assert exc.value.detail["database"] is True
    assert exc.value.detail["redis"] is False
