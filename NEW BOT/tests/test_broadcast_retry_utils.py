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
    classified = classify_telegram_error(
        "Telegram says: [420 SLOWMODE_WAIT]", slowmode_default_seconds=300
    )
    assert classified["retriable"] is True
    assert classified["retry_after_seconds"] == 300


def test_flood_message_is_retriable():
    classified = classify_telegram_error("FLOOD_WAIT_120")
    assert classified["retriable"] is True


def test_slowmode_wait_seconds_are_parsed_from_message():
    classified = classify_telegram_error("Telegram says: [420 SLOWMODE_WAIT_3]")
    assert classified["retriable"] is True
    assert classified["retry_after_seconds"] == 3


def test_flood_wait_seconds_are_parsed_from_message():
    classified = classify_telegram_error("FLOOD_WAIT_17")
    assert classified["retriable"] is True
    assert classified["retry_after_seconds"] == 17


def test_retry_after_is_read_from_exception_value_attr():
    class _FakeFloodError(Exception):
        def __init__(self, value: int):
            self.value = value
            super().__init__("FLOOD_WAIT")

    classified = classify_telegram_error(_FakeFloodError(42))
    assert classified["retriable"] is True
    assert classified["retry_after_seconds"] == 42
