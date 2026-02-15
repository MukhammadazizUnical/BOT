from app.utils import classify_telegram_error, compute_retry_delay_ms


def test_provider_retry_after_is_hard_lower_bound():
    delay = compute_retry_delay_ms(
        retry_count=1,
        retry_after_seconds=300,
        base_delay_ms=2000,
        max_delay_ms=120000,
        jitter_ratio=0,
    )
    assert delay >= 300000


def test_slowmode_without_retry_after_uses_default_seconds():
    classified = classify_telegram_error("SLOWMODE_WAIT_10", slowmode_default_seconds=300)
    assert classified["retriable"] is True
    assert classified["retry_after_seconds"] == 300


def test_flood_message_is_retriable():
    classified = classify_telegram_error("FLOOD_WAIT_120")
    assert classified["retriable"] is True
