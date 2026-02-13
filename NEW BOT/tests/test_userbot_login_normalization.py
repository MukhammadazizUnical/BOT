from app.services.userbot_service import UserbotService


def test_normalize_phone_strips_symbols_and_prefixes_plus():
    svc = UserbotService()
    assert svc._normalize_phone("(+996) 552-272-029") == "+996552272029"
    assert svc._normalize_phone("00996552272029") == "+996552272029"


def test_normalize_code_keeps_digits_only():
    svc = UserbotService()
    assert svc._normalize_code("1 2 3 4 5") == "12345"
    assert svc._normalize_code("12-34-5") == "12345"
