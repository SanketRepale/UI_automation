"""Background worker for Playwright test execution using RQ."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import redis
from rq import Worker, Queue, Connection

from ui_automation.config import settings
from ui_automation.database import Database
from ui_automation.repository import Repository
from ui_automation.executor import ExecutionService
from ui_automation.utils import configure_logging, log_event


def execute_test_case_job(job_data: dict) -> dict:
    """Execute a single test case in the background."""
    settings.prepare()
    database = Database(settings.database_path)
    repository = Repository(database)
    logger = configure_logging(settings.reports_dir)

    case_id = job_data["case_id"]
    run_id = job_data["run_id"]
    case = job_data["case"]
    target_url = job_data["target_url"]
    browser = job_data["browser"]
    authentication = job_data.get("authentication")
    locators = job_data.get("locators", [])

    log_event(logger, "Worker", "job_started", run_id=run_id, case_id=case_id)

    try:
        outcome = ExecutionService(settings).run_case(
            case, run_id, locators, target_url, browser, authentication=authentication
        )
        repository.save_result(
            run_id, case_id, outcome["status"], outcome["duration"],
            outcome["error"], {"source": "worker"}, outcome["steps"]
        )
        log_event(logger, "Worker", "job_completed", run_id=run_id, case_id=case_id, status=outcome["status"])
        return {"status": "completed", "outcome": outcome}
    except Exception as e:
        log_event(logger, "Worker", "job_failed", run_id=run_id, case_id=case_id, error=str(e))
        return {"status": "failed", "error": str(e)}


def main():
    """Main worker entry point."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    conn = redis.from_url(redis_url)

    with Connection(conn):
        queue = Queue("executions", connection=conn)
        worker = Worker([queue], connection=conn)
        worker.work()


if __name__ == "__main__":
    main()