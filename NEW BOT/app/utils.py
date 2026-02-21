import math
import random
import re
from datetime import datetime, timedelta


RETRIABLE_ERROR_TOKENS = (
    "FLOOD_WAIT",
    "FLOOD",
    "SLOWMODE_WAIT",
    "TIMEOUT",
    "ETIMEDOUT",
)
TERMINAL_REASON_TOKENS = (
    "CHAT_WRITE_FORBIDDEN",
    "USER_BANNED_IN_CHANNEL",
    "CHANNEL_PRIVATE",
    "CHAT_ADMIN_REQUIRED",
    "PEER_ID_INVALID",
    "USER_DEACTIVATED",
    "BOT_WAS_BLOCKED",
    "INPUT_USER_DEACTIVATED",
)


def normalize_error_message(error: Exception | str | object) -> str:
    if isinstance(error, Exception):
        return str(error)
    return str(error)


def classify_telegram_error(
    error: Exception | str | object, slowmode_default_seconds: int = 300
) -> dict:
    msg = normalize_error_message(error).upper()
    retry_after_seconds = None

    for attr in ("seconds", "value"):
        raw_value = getattr(error, attr, None)
        parsed_value = None
        if isinstance(raw_value, int):
            parsed_value = raw_value
        elif isinstance(raw_value, str) and raw_value.isdigit():
            parsed_value = int(raw_value)

        if isinstance(parsed_value, int) and parsed_value > 0:
            retry_after_seconds = parsed_value
            break

    if retry_after_seconds is None:
        match = re.search(r"WAIT OF\s+(\d+)\s+SECONDS", msg)
        if match:
            value = int(match.group(1))
            retry_after_seconds = value if value > 0 else None

    if retry_after_seconds is None:
        match = re.search(r"(?:SLOWMODE_WAIT|FLOOD_WAIT)_([0-9]+)", msg)
        if match:
            value = int(match.group(1))
            retry_after_seconds = value if value > 0 else None

    if retry_after_seconds is None and "SLOWMODE_WAIT" in msg:
        retry_after_seconds = max(1, int(slowmode_default_seconds))

    if any(token in msg for token in RETRIABLE_ERROR_TOKENS):
        return {
            "retriable": True,
            "terminal_code": "retriable-rate-limit",
            "retry_after_seconds": retry_after_seconds,
        }

    terminal = next((t for t in TERMINAL_REASON_TOKENS if t in msg), None)
    if terminal:
        return {
            "retriable": False,
            "terminal_code": terminal.lower(),
            "retry_after_seconds": None,
        }

    return {
        "retriable": False,
        "terminal_code": "unknown",
        "retry_after_seconds": None,
    }


def compute_retry_delay_ms(
    retry_count: int,
    retry_after_seconds: int | None,
    base_delay_ms: int,
    max_delay_ms: int,
    jitter_ratio: float,
) -> int:
    exponential = min(max_delay_ms, base_delay_ms * (2**retry_count))
    provider_delay = (retry_after_seconds or 0) * 1000

    # Provider-mandated wait (e.g. slow mode / flood wait) must not be clamped
    # by local max backoff; otherwise 5m waits get retried too early.
    if provider_delay > 0:
        jitter_range = max(0, math.floor(provider_delay * jitter_ratio))
        jitter = random.randint(0, jitter_range) if jitter_range > 0 else 0
        return provider_delay + jitter

    jitter_range = max(0, math.floor(exponential * jitter_ratio))
    jitter = random.randint(0, jitter_range) if jitter_range > 0 else 0
    return min(max_delay_ms, exponential + jitter)


def build_attempt_idempotency_key(campaign_id: str, target_group_id: str) -> str:
    return f"{campaign_id}:{target_group_id}"


def utcnow() -> datetime:
    return datetime.utcnow()


def now_plus_ms(ms: int) -> datetime:
    return utcnow() + timedelta(milliseconds=ms)


def deterministic_jitter_ms(user_id: str, run_slot: int, jitter_max_ms: int) -> int:
    if jitter_max_ms <= 0:
        return 0
    raw = f"{user_id}:{run_slot}"
    h = 0
    for ch in raw:
        h = ((h * 31) + ord(ch)) & 0xFFFFFFFF
    return h % (jitter_max_ms + 1)
