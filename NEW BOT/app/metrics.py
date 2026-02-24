from threading import Lock
import re

from app.redis_client import redis_client


COUNTERS_KEY = "metrics:counters"
GAUGES_KEY = "metrics:gauges"
LEGACY_COUNTER_KEYS = {
    "processor.result.success",
    "processor.result.failed",
    "processor.result.total",
    "processor.started",
    "processor.lock_busy",
    "processor.continuation.enqueued",
    "processor.skipped_non_worker",
    "worker.startup.count",
}
LEGACY_GAUGE_KEYS = {
    "processor.last_lag_ms",
    "processor.last_sent_count",
    "worker.last_job_lag_ms",
    "queue.last_enqueue_delay_ms",
    "scheduler.last_enqueued_count",
}


def metric_key(name: str, **labels: str | int | float | bool) -> str:
    if not labels:
        return name
    parts = [name]
    for key in sorted(labels):
        value = str(labels[key]).strip().replace("|", "_").replace("=", "_")
        parts.append(f"{key}={value}")
    return "|".join(parts)


class MetricsStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, int | float] = {}

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = int(self._counters.get(name, 0)) + int(value)

    def set_gauge(self, name: str, value: int | float) -> None:
        with self._lock:
            self._gauges[name] = value

    def snapshot(self) -> dict[str, dict[str, int | float]]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
            }

    @staticmethod
    def _prom_name(name: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_:]", "_", str(name))
        if not re.match(r"^[a-zA-Z_:]", normalized):
            normalized = f"m_{normalized}"
        return normalized

    def to_prometheus_text(self) -> str:
        snap = self.snapshot()
        lines: list[str] = []

        def parse_metric(raw_name: str) -> tuple[str, dict[str, str]]:
            if "|" not in raw_name:
                return raw_name, {}
            chunks = [chunk for chunk in raw_name.split("|") if chunk]
            if not chunks:
                return raw_name, {}
            base = chunks[0]
            labels: dict[str, str] = {}
            for chunk in chunks[1:]:
                if "=" not in chunk:
                    continue
                key, value = chunk.split("=", 1)
                labels[self._prom_name(key)] = value.replace('"', "'")
            return base, labels

        def format_sample(name: str, labels: dict[str, str], value: int | float) -> str:
            safe_name = self._prom_name(name)
            if not labels:
                return f"{safe_name} {value}"
            rendered = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            return f"{safe_name}{{{rendered}}} {value}"

        counters = snap.get("counters", {})
        for raw_name, value in sorted(counters.items()):
            name, labels = parse_metric(raw_name)
            safe_name = self._prom_name(name)
            lines.append(f"# TYPE {safe_name} counter")
            lines.append(format_sample(name, labels, int(value)))

        gauges = snap.get("gauges", {})
        for raw_name, value in sorted(gauges.items()):
            name, labels = parse_metric(raw_name)
            safe_name = self._prom_name(name)
            lines.append(f"# TYPE {safe_name} gauge")
            lines.append(format_sample(name, labels, value))

        if not lines:
            lines.append("# no_metrics 1")
        return "\n".join(lines) + "\n"


metrics_store = MetricsStore()


async def inc_metric(name: str, value: int = 1) -> None:
    metrics_store.inc(name, value)
    try:
        await redis_client.hincrby(COUNTERS_KEY, name, int(value))
    except Exception:
        return


async def set_gauge_metric(name: str, value: int | float) -> None:
    metrics_store.set_gauge(name, value)
    try:
        await redis_client.hset(GAUGES_KEY, name, value)
    except Exception:
        return


def _coerce_number(raw) -> int | float:
    text = str(raw)
    try:
        if "." in text:
            return float(text)
        return int(text)
    except Exception:
        return 0


async def global_snapshot() -> dict[str, dict[str, int | float]]:
    local = metrics_store.snapshot()
    try:
        raw_counters = await redis_client.hgetall(COUNTERS_KEY)
        raw_gauges = await redis_client.hgetall(GAUGES_KEY)
    except Exception:
        return local

    counters: dict[str, int | float] = {k: int(_coerce_number(v)) for k, v in raw_counters.items()}
    gauges: dict[str, int | float] = {k: _coerce_number(v) for k, v in raw_gauges.items()}

    def prune_legacy_unlabeled(
        items: dict[str, int | float],
        legacy_keys: set[str],
    ) -> dict[str, int | float]:
        keys = list(items.keys())
        for key in keys:
            if key in legacy_keys:
                items.pop(key, None)
                continue
            if "|" in key:
                continue
            labeled_prefix = f"{key}|"
            if any(other.startswith(labeled_prefix) for other in keys):
                items.pop(key, None)
        return items

    counters = prune_legacy_unlabeled(counters, LEGACY_COUNTER_KEYS)
    gauges = prune_legacy_unlabeled(gauges, LEGACY_GAUGE_KEYS)

    if not counters and not gauges:
        return local

    result: dict[str, dict[str, int | float]] = {
        "counters": counters,
        "gauges": gauges,
    }
    return result


async def global_prometheus_text() -> str:
    snap = await global_snapshot()
    temp = MetricsStore()
    for key, value in snap.get("counters", {}).items():
        temp.inc(key, int(value))
    for key, value in snap.get("gauges", {}).items():
        temp.set_gauge(key, value)
    return temp.to_prometheus_text()
