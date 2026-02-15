from datetime import datetime, timedelta

from app.services.userbot_service import UserbotService


def test_cycle_cutoff_uses_interval_seconds():
    now = datetime(2026, 2, 15, 12, 0, 0)
    cutoff = UserbotService.cycle_cutoff(now, 300)
    assert cutoff == now - timedelta(seconds=300)


def test_interval_elapsed_blocks_early_retry():
    now = datetime(2026, 2, 15, 12, 0, 0)
    sent_at = now - timedelta(seconds=299)
    assert UserbotService.is_interval_elapsed(sent_at, 300, now) is False


def test_interval_elapsed_allows_next_cycle_after_boundary():
    now = datetime(2026, 2, 15, 12, 0, 0)
    sent_at = now - timedelta(seconds=300)
    assert UserbotService.is_interval_elapsed(sent_at, 300, now) is True


def test_retry_exhaustion_threshold():
    assert UserbotService.is_retry_exhausted(next_retry_count=4, max_retries=3) is True
    assert UserbotService.is_retry_exhausted(next_retry_count=3, max_retries=3) is False
