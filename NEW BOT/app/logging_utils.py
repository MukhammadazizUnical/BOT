import json
import logging
from datetime import datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_json_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if getattr(root, "_json_logging_configured", False):
        return

    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    setattr(root, "_json_logging_configured", True)


def log_event(logger: logging.Logger, level: int, event: str, **fields) -> None:
    payload = {
        "event": event,
        **fields,
    }
    logger.log(level, json.dumps(payload, default=str))
