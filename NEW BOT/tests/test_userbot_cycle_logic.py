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


def test_should_retry_retriable_keeps_retrying_for_slowmode_even_after_max():
    classified = {"retriable": True, "is_slowmode": True}
    assert (
        UserbotService.should_retry_retriable(
            classified=classified,
            next_retry_count=99,
            max_retries=3,
        )
        is True
    )


def test_should_retry_retriable_stops_non_slowmode_after_max():
    classified = {"retriable": True, "is_slowmode": False}
    assert (
        UserbotService.should_retry_retriable(
            classified=classified,
            next_retry_count=4,
            max_retries=3,
        )
        is False
    )


def test_compute_cycle_next_due_uses_queued_at_anchor():
    due = UserbotService.compute_cycle_next_due(
        queued_at="2026-02-24T08:35:00Z",
        cycle_interval_seconds=300,
    )
    assert due == datetime(2026, 2, 24, 8, 40, 0)


def test_compute_cycle_next_due_falls_back_to_now_for_invalid_queued_at():
    base = datetime(2026, 2, 24, 8, 35, 0)
    due = UserbotService.compute_cycle_next_due(
        queued_at="invalid",
        cycle_interval_seconds=300,
        fallback_now=base,
    )
    assert due == datetime(2026, 2, 24, 8, 40, 0)
