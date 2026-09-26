from __future__ import annotations

import uuid
from typing import Any

from ui_automation.database import Database


class Repository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def save_requirement(self, requirement_id: str, title: str, story: str, criteria: list[str], analysis: dict[str, Any], files: list[str]) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO requirements(id,title,user_story,acceptance_criteria,analysis,source_files,created_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title,user_story=excluded.user_story,acceptance_criteria=excluded.acceptance_criteria,analysis=excluded.analysis,source_files=excluded.source_files",
                (requirement_id, title, story, self.db.encode(criteria), self.db.encode(analysis), self.db.encode(files), self.db.now()),
            )

    def requirements(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM requirements ORDER BY created_at DESC").fetchall()
        return [{**dict(row), "acceptance_criteria": self.db.decode(row["acceptance_criteria"], []), "analysis": self.db.decode(row["analysis"], {}), "source_files": self.db.decode(row["source_files"], [])} for row in rows]

    def delete_requirement(self, requirement_id: str) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM locators WHERE requirement_id=?", (requirement_id,))
            connection.execute("DELETE FROM requirements WHERE id=?", (requirement_id,))

    def save_requirement_target(self, target: dict[str, Any]) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO requirement_targets(requirement_id,application_url,authentication_type,browser,headless,username_label,password_label,submit_label,guidance,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(requirement_id) DO UPDATE SET application_url=excluded.application_url,authentication_type=excluded.authentication_type,browser=excluded.browser,headless=excluded.headless,username_label=excluded.username_label,password_label=excluded.password_label,submit_label=excluded.submit_label,guidance=excluded.guidance,updated_at=excluded.updated_at",
                (target["requirement_id"], target["application_url"], target.get("authentication_type", "No Authentication"), target.get("browser", "chromium"), int(target.get("headless", True)), target.get("username_label", ""), target.get("password_label", ""), target.get("submit_label", ""), target.get("guidance", ""), self.db.now()),
            )

    def requirement_target(self, requirement_id: str) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM requirement_targets WHERE requirement_id=?", (requirement_id,)).fetchone()
        return {**dict(row), "headless": bool(row["headless"])} if row else None

    def save_application_config(self, config: dict[str, Any]) -> None:
        config_id = config.get("id") or str(uuid.uuid4())
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO application_configs(id,name,application_url,authentication_type,environment,browser,headless,username_label,password_label,submit_label,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET application_url=excluded.application_url,authentication_type=excluded.authentication_type,environment=excluded.environment,browser=excluded.browser,headless=excluded.headless,username_label=excluded.username_label,password_label=excluded.password_label,submit_label=excluded.submit_label,updated_at=excluded.updated_at",
                (config_id, config["name"], config["application_url"], config["authentication_type"], config["environment"], config["browser"], int(config["headless"]), config.get("username_label", ""), config.get("password_label", ""), config.get("submit_label", ""), self.db.now(), self.db.now()),
            )

    def application_configs(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM application_configs ORDER BY name").fetchall()
        return [{**dict(row), "headless": bool(row["headless"])} for row in rows]

    def delete_application_config(self, config_id: str) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM application_configs WHERE id=?", (config_id,))

    def save_test_case(self, case: dict[str, Any]) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO test_cases(id,requirement_id,title,test_type,priority,status,payload,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET requirement_id=excluded.requirement_id,title=excluded.title,test_type=excluded.test_type,priority=excluded.priority,status=excluded.status,payload=excluded.payload,updated_at=excluded.updated_at",
                (case["id"], case["requirement_id"], case["title"], case.get("test_type", "Functional"), case.get("priority", "Medium"), case.get("status", "Draft"), self.db.encode(case), self.db.now()),
            )

    def delete_test_case(self, test_case_id: str) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM locators WHERE test_case_id=?", (test_case_id,))
            connection.execute("DELETE FROM test_cases WHERE id=?", (test_case_id,))

    def test_cases(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT payload FROM test_cases ORDER BY updated_at DESC").fetchall()
        return [self.db.decode(row["payload"], {}) for row in rows]

    def create_suite(self, name: str, description: str = "") -> str:
        suite_id = str(uuid.uuid4())
        with self.db.connect() as connection:
            connection.execute("INSERT INTO test_suites(id,name,description,created_at) VALUES(?,?,?,?)", (suite_id, name, description, self.db.now()))
        return suite_id

    def suites(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT s.*, COUNT(sc.test_case_id) AS case_count FROM test_suites s LEFT JOIN suite_cases sc ON sc.suite_id=s.id GROUP BY s.id ORDER BY s.name").fetchall()
        return [dict(row) for row in rows]

    def delete_suite(self, suite_id: str) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM test_suites WHERE id=?", (suite_id,))

    def suite_case_ids(self, suite_id: str) -> list[str]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT test_case_id FROM suite_cases WHERE suite_id=? ORDER BY test_case_id", (suite_id,)).fetchall()
        return [row["test_case_id"] for row in rows]

    def set_suite_cases(self, suite_id: str, test_case_ids: list[str]) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM suite_cases WHERE suite_id=?", (suite_id,))
            connection.executemany("INSERT INTO suite_cases(suite_id,test_case_id) VALUES(?,?)", [(suite_id, test_case_id) for test_case_id in test_case_ids])

    def locators(self, test_case_id: str | None = None, requirement_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM locators"
        params: tuple[Any, ...] = ()
        if test_case_id:
            if requirement_id:
                query += " WHERE test_case_id=? OR (test_case_id IS NULL AND (requirement_id=? OR requirement_id IS NULL))"
                params = (test_case_id, requirement_id)
            else:
                query += " WHERE test_case_id = ? OR test_case_id IS NULL"
                params = (test_case_id,)
        elif requirement_id:
            query += " WHERE requirement_id=? AND test_case_id IS NULL"
            params = (requirement_id,)
        query += " ORDER BY element"
        with self.db.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        output = []
        for row in rows:
            entry = dict(row)
            entry["candidates"] = self.db.decode(entry["candidates"], [])
            entry["validated"] = bool(entry["validated"])
            entry["xpath"] = next((candidate["value"] for candidate in entry["candidates"] if candidate.get("kind") == "xpath"), "")
            output.append(entry)
        return output

    def save_locator(self, item: dict[str, Any]) -> None:
        with self.db.connect() as connection:
            locator_id = item.get("id")
            if not locator_id:
                existing = connection.execute(
                    "SELECT id FROM locators WHERE requirement_id IS ? AND test_case_id IS ? AND page_url=? AND element=? LIMIT 1",
                    (item.get("requirement_id"), item.get("test_case_id"), item["page_url"], item["element"]),
                ).fetchone()
                locator_id = existing["id"] if existing else str(uuid.uuid4())
            connection.execute(
                "INSERT INTO locators(id,requirement_id,test_case_id,page_url,element,candidates,selected,confidence,validated,last_validated,explanation) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET page_url=excluded.page_url,element=excluded.element,candidates=excluded.candidates,selected=excluded.selected,confidence=excluded.confidence,validated=excluded.validated,last_validated=excluded.last_validated,explanation=excluded.explanation",
                (locator_id, item.get("requirement_id"), item.get("test_case_id"), item["page_url"], item["element"], self.db.encode(item.get("candidates", [])), item.get("selected", ""), item.get("confidence", 0), int(item.get("validated", False)), item.get("last_validated"), item.get("explanation", "")),
            )

    def save_script(self, test_case_id: str, source: str) -> str:
        script_id = str(uuid.uuid4())
        with self.db.connect() as connection:
            connection.execute("INSERT INTO scripts(id,test_case_id,source,updated_at) VALUES(?,?,?,?)", (script_id, test_case_id, source, self.db.now()))
        return script_id

    def latest_script(self, test_case_id: str) -> str | None:
        with self.db.connect() as connection:
            row = connection.execute("SELECT source FROM scripts WHERE test_case_id=? ORDER BY updated_at DESC LIMIT 1", (test_case_id,)).fetchone()
        return row["source"] if row else None

    def create_run(self, run_id: str, environment: str, browser: str) -> None:
        with self.db.connect() as connection:
            connection.execute("INSERT INTO execution_runs(id,started_at,environment,browser,status) VALUES(?,?,?,?,?)", (run_id, self.db.now(), environment, browser, "RUNNING"))

    def finish_run(self, run_id: str, summary: dict[str, Any]) -> None:
        with self.db.connect() as connection:
            connection.execute("UPDATE execution_runs SET finished_at=?,status=?,summary=? WHERE id=?", (self.db.now(), "COMPLETED", self.db.encode(summary), run_id))

    def save_result(self, run_id: str, case_id: str, status: str, duration: float, error: str, details: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        result_id = str(uuid.uuid4())
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO test_results(id,run_id,test_case_id,status,duration,error,details) VALUES(?,?,?,?,?,?,?)",
                (result_id, run_id, case_id, status or "PASS", float(duration or 0.0), str(error or ""), self.db.encode(details or {})),
            )
            for step in steps:
                connection.execute(
                    "INSERT INTO step_results(id,test_result_id,step_number,action,expected,actual,status,started_at,ended_at,duration,locator,error,screenshot_path,before_screenshot_path,page_url,page_title) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()),
                        result_id,
                        int(step.get("step_number") or 0),
                        str(step.get("action") or ""),
                        str(step.get("expected") or ""),
                        str(step.get("actual") or ""),
                        str(step.get("status") or "BLOCKED"),
                        str(step.get("started_at") or self.db.now()),
                        str(step.get("ended_at") or self.db.now()),
                        float(step.get("duration") or 0.0),
                        str(step.get("locator") or ""),
                        str(step.get("error") or ""),
                        str(step.get("screenshot_path") or ""),
                        str(step.get("before_screenshot_path") or ""),
                        str(step.get("page_url") or ""),
                        str(step.get("page_title") or ""),
                    ),
                )

    def history(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM execution_runs ORDER BY started_at DESC").fetchall()
        return [{**dict(row), "summary": self.db.decode(row["summary"], {})} for row in rows]

    def results(self, run_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT r.*, c.title, c.requirement_id, c.priority, c.test_type, e.started_at AS run_started_at, e.browser, e.environment FROM test_results r LEFT JOIN test_cases c ON c.id=r.test_case_id LEFT JOIN execution_runs e ON e.id=r.run_id"
        params: tuple[Any, ...] = ()
        if run_id:
            query += " WHERE r.run_id=?"
            params = (run_id,)
        query += " ORDER BY r.rowid DESC"
        with self.db.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def step_results(self, test_result_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM step_results WHERE test_result_id=? ORDER BY step_number", (test_result_id,)).fetchall()
        return [dict(row) for row in rows]
