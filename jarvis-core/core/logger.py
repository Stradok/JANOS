import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        entry = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra"):
            entry["extra"] = record.extra
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logger(name: str = "jarvis", log_dir: str | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setLevel(logging.INFO)
    stdout.setFormatter(StructuredFormatter())
    logger.addHandler(stdout)

    if log_dir:
        p = Path(log_dir)
        p.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(p / "jarvis.jsonl"))
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(StructuredFormatter())
        logger.addHandler(fh)

    return logger


def get_logger(name: str = "jarvis") -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **extra: Any) -> None:
    logger.info(event, extra={"extra": extra})
