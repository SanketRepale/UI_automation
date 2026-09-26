from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload.update(event_data)
        else:
            payload["message"] = record.getMessage()
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


class TerminalEventFilter(logging.Filter):
    visible_actions = {
        "requirement_analyzed",
        "requirement_deleted",
        "test_case_deleted",
        "application_profile_saved",
        "test_case_generation_started",
        "test_case_generation_completed",
        "locator_discovery_started",
        "locator_discovery_completed",
        "script_generation_started",
        "script_generation_completed",
        "execution_run_started",
        "execution_run_finished",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        event_data = getattr(record, "event_data", {})
        action = event_data.get("action", "") if isinstance(event_data, dict) else ""
        if action in {"screenshot_failed", "before_screenshot_failed"}:
            return False
        return record.levelno >= logging.WARNING or action in self.visible_actions


class TerminalEventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event_data = getattr(record, "event_data", {})
        if not isinstance(event_data, dict):
            return f"{record.levelname}: {record.getMessage()}"
        agent = event_data.get("agent", record.name)
        action = str(event_data.get("action", record.getMessage())).replace("_", " ")
        fields = " ".join(
            f"{key}={str(value)[:240]}"
            for key, value in event_data.items()
            if key not in {"agent", "action"} and value is not None
        )
        return f"{record.levelname} [{agent}] {action}" + (f" | {fields}" if fields else "")


def log_event(logger: logging.Logger, agent: str, action: str, *, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, action, extra={"event_data": {"agent": agent, "action": action, **fields}})


def configure_logging(directory: Path) -> logging.Logger:
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ui_automation")
    log_path = (directory / "automation.log").resolve()
    handler = next((item for item in logger.handlers if isinstance(item, RotatingFileHandler) and Path(item.baseFilename) == log_path), None)
    if handler is None:
        handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        logger.addHandler(handler)
    handler.setFormatter(JsonLineFormatter())
    console_handler = next((item for item in logger.handlers if getattr(item, "ui_automation_console", False)), None)
    if console_handler is None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.ui_automation_console = True
        console_handler.addFilter(TerminalEventFilter())
        logger.addHandler(console_handler)
    console_handler.setFormatter(TerminalEventFormatter())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
