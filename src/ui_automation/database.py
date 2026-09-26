from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS requirements (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, user_story TEXT NOT NULL DEFAULT '',
 acceptance_criteria TEXT NOT NULL DEFAULT '[]', analysis TEXT NOT NULL DEFAULT '{}',
 source_files TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS application_configs (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, application_url TEXT NOT NULL,
 authentication_type TEXT NOT NULL, environment TEXT NOT NULL, browser TEXT NOT NULL,
 headless INTEGER NOT NULL, username_label TEXT NOT NULL DEFAULT '',
 password_label TEXT NOT NULL DEFAULT '', submit_label TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requirement_targets (
 requirement_id TEXT PRIMARY KEY REFERENCES requirements(id) ON DELETE CASCADE,
 application_url TEXT NOT NULL, authentication_type TEXT NOT NULL DEFAULT 'No Authentication',
 browser TEXT NOT NULL DEFAULT 'chromium', headless INTEGER NOT NULL DEFAULT 1,
 username_label TEXT NOT NULL DEFAULT '', password_label TEXT NOT NULL DEFAULT '',
 submit_label TEXT NOT NULL DEFAULT '', guidance TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_cases (
 id TEXT PRIMARY KEY, requirement_id TEXT NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
 title TEXT NOT NULL, test_type TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Draft',
 payload TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_suites (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suite_cases (
 suite_id TEXT NOT NULL REFERENCES test_suites(id) ON DELETE CASCADE,
 test_case_id TEXT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
 PRIMARY KEY(suite_id, test_case_id)
);
CREATE TABLE IF NOT EXISTS locators (
 id TEXT PRIMARY KEY, requirement_id TEXT, test_case_id TEXT, page_url TEXT NOT NULL,
 element TEXT NOT NULL, candidates TEXT NOT NULL, selected TEXT NOT NULL DEFAULT '',
 confidence REAL NOT NULL DEFAULT 0, validated INTEGER NOT NULL DEFAULT 0,
 last_validated TEXT, explanation TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS scripts (
 id TEXT PRIMARY KEY, test_case_id TEXT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
 source TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_runs (
 id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, environment TEXT NOT NULL,
 browser TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS test_results (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES execution_runs(id) ON DELETE CASCADE,
 test_case_id TEXT NOT NULL, status TEXT NOT NULL, duration REAL NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS step_results (
 id TEXT PRIMARY KEY, test_result_id TEXT NOT NULL REFERENCES test_results(id) ON DELETE CASCADE,
 step_number INTEGER NOT NULL, action TEXT NOT NULL, expected TEXT NOT NULL DEFAULT '', actual TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL, duration REAL NOT NULL DEFAULT 0,
 locator TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', screenshot_path TEXT NOT NULL DEFAULT '', before_screenshot_path TEXT NOT NULL DEFAULT '',
 page_url TEXT NOT NULL DEFAULT '', page_title TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_test_results_run ON test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_step_results_parent ON step_results(test_result_id);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(step_results)")}
            if "before_screenshot_path" not in columns:
                connection.execute("ALTER TABLE step_results ADD COLUMN before_screenshot_path TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, default=str)

    @staticmethod
    def decode(value: str, fallback: Any = None) -> Any:
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()
