from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ui_automation.api import _browser_execution_enabled, create_app
from ui_automation.config import Settings, _env_int, _runtime_data_dir
from ui_automation.database import Database
from ui_automation.repository import Repository


def test_empty_or_invalid_integer_environment_values_use_defaults(monkeypatch) -> None:
    monkeypatch.setenv("TIMEOUT_MS", "")
    assert _env_int("TIMEOUT_MS", 10000) == 10000
    monkeypatch.setenv("TIMEOUT_MS", "not-a-number")
    assert _env_int("TIMEOUT_MS", 10000) == 10000


def test_vercel_uses_writable_runtime_data_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATA_DIR", raising=False)
    assert _runtime_data_dir() == Path("/tmp/ui-automation")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert _runtime_data_dir() == tmp_path


def test_browser_operations_are_disabled_on_vercel_without_worker(monkeypatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("EXECUTION_ENABLED", raising=False)
    assert not _browser_execution_enabled()
    monkeypatch.setenv("EXECUTION_ENABLED", "true")
    assert not _browser_execution_enabled()
    monkeypatch.setenv("VERCEL", "")
    assert _browser_execution_enabled()


def test_vercel_rejects_upload_batches_over_request_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    app_settings = Settings(database_path=tmp_path / "size.db", uploads_dir=tmp_path / "uploads", evidence_dir=tmp_path / "evidence", scripts_dir=tmp_path / "scripts", reports_dir=tmp_path / "reports")
    client = TestClient(create_app(app_settings))
    content = b"x" * (4 * 1024 * 1024 + 1)
    response = client.post("/api/requirements/analyze", files={"files": ("large.txt", content, "text/plain")})
    assert response.status_code == 413


def test_run_evidence_export_contains_run_and_step_records(tmp_path: Path) -> None:
    app_settings = Settings(database_path=tmp_path / "evidence.db", uploads_dir=tmp_path / "uploads", evidence_dir=tmp_path / "evidence", scripts_dir=tmp_path / "scripts", reports_dir=tmp_path / "reports")
    client = TestClient(create_app(app_settings))
    repository = Repository(Database(app_settings.database_path))
    repository.save_requirement("REQ-EVIDENCE", "Evidence", "Story", [], {}, [])
    repository.save_test_case({"id": "TC-EVIDENCE", "requirement_id": "REQ-EVIDENCE", "title": "Evidence case", "steps": []})
    repository.create_run("RUN-EVIDENCE", "QA", "chromium")
    repository.save_result("RUN-EVIDENCE", "TC-EVIDENCE", "PASS", 0.4, "", {}, [{"step_number": 1, "action": "Open page", "status": "PASS"}])
    repository.finish_run("RUN-EVIDENCE", {"PASS": 1, "total": 1})

    response = client.get("/api/export/evidence/RUN-EVIDENCE")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"


def test_api_health_and_story_target_round_trip(tmp_path: Path) -> None:
    app_settings = Settings(database_path=tmp_path / "api.db", uploads_dir=tmp_path / "uploads", evidence_dir=tmp_path / "evidence", scripts_dir=tmp_path / "scripts", reports_dir=tmp_path / "reports")
    client = TestClient(create_app(app_settings))
    assert client.get("/api/health").json()["status"] == "ok"

    document = b"User Story: A user signs in.\nAcceptance Criteria:\n1. Sign in works.\nWeb Application URL: https://example.test/login"
    response = client.post("/api/requirements/analyze", files={"files": ("story.txt", document, "text/plain")})
    assert response.status_code == 200
    requirement = response.json()["requirement"]
    requirement_id = requirement["id"]

    target = client.put(f"/api/requirements/{requirement_id}/target", json={"application_url": "https://example.test/login", "authentication_type": "No Authentication", "browser": "chromium", "headless": True})
    assert target.status_code == 200
    assert target.json()["application_url"] == "https://example.test/login"


def test_uploaded_story_credentials_return_only_as_session_material(tmp_path: Path) -> None:
    app_settings = Settings(database_path=tmp_path / "credentials.db", uploads_dir=tmp_path / "uploads", evidence_dir=tmp_path / "evidence", scripts_dir=tmp_path / "scripts", reports_dir=tmp_path / "reports")
    client = TestClient(create_app(app_settings))
    document = b"User Story: Sign in.\nAcceptance Criteria:\n1. Valid credentials open the workspace.\nWeb Application URL: https://example.test/login\nAuthentication: Username & Password\nUsername: member@example.test\nPassword: session-secret"
    response = client.post("/api/requirements/analyze", files={"files": ("auth.txt", document, "text/plain")})
    assert response.status_code == 200
    assert response.json()["session_credentials"] == {"username": "member@example.test", "password": "session-secret"}
    requirement = response.json()["requirement"]
    assert "session-secret" not in str(requirement)
    assert "member@example.test" not in str(requirement)


def test_api_rejects_invalid_target_url(tmp_path: Path) -> None:
    app_settings = Settings(database_path=tmp_path / "api.db", uploads_dir=tmp_path / "uploads", evidence_dir=tmp_path / "evidence", scripts_dir=tmp_path / "scripts", reports_dir=tmp_path / "reports")
    client = TestClient(create_app(app_settings))
    response = client.put("/api/requirements/missing/target", json={"application_url": "not-a-url"})
    assert response.status_code == 422


def test_case_review_script_suite_and_export_workflow(tmp_path: Path) -> None:
    app_settings = Settings(database_path=tmp_path / "workflow.db", uploads_dir=tmp_path / "uploads", evidence_dir=tmp_path / "evidence", scripts_dir=tmp_path / "scripts", reports_dir=tmp_path / "reports")
    client = TestClient(create_app(app_settings))
    document = b"User Story: A member signs in.\nAcceptance Criteria:\n1. Valid credentials open the workspace.\n2. Invalid credentials show an error."
    analysis = client.post("/api/requirements/analyze", files={"files": ("auth.txt", document, "text/plain")})
    requirement_id = analysis.json()["requirement"]["id"]
    generated = client.post(f"/api/requirements/{requirement_id}/generate").json()["cases"]
    assert generated
    case = generated[0]

    updated = client.put(f"/api/cases/{case['id']}", json={**case, "status": "Approved", "steps": [{"number": 1, "action": "Verify workspace"}]})
    assert updated.status_code == 200
    assert updated.json()["status"] == "Approved"
    assert client.get("/api/cases", params={"status_filter": "Approved"}).json()[0]["id"] == case["id"]

    saved_script = client.put(f"/api/cases/{case['id']}/script", json={"source": "print('reviewed')"})
    assert saved_script.status_code == 200
    assert client.get(f"/api/cases/{case['id']}/script").json()["source"] == "print('reviewed')"
    assert client.put(f"/api/cases/{case['id']}/script", json={"source": "if:"}).status_code == 422

    suite = client.post("/api/suites", json={"name": "Auth smoke", "description": "Sign-in checks", "case_ids": [case["id"]]})
    assert suite.status_code == 200
    assert suite.json()["case_ids"] == [case["id"]]
    assert client.get("/api/suites").json()[0]["name"] == "Auth smoke"
    assert client.get("/api/export/cases", params={"format": "csv"}).headers["content-type"].startswith("text/csv")
    assert case["id"] in client.get("/api/export/cases", params={"format": "json", "requirement_id": requirement_id, "status_filter": "Approved"}).text
    assert client.get("/api/export/cases", params={"format": "xlsx"}).content.startswith(b"PK")
    assert client.get("/api/report").json()["counts"] == {}
    assert client.get("/api/export/report", params={"format": "csv"}).headers["content-type"].startswith("text/csv")

    review = client.get(f"/api/cases/{case['id']}/review")
    assert review.status_code == 200
    assert "issues" in review.json()
    assert "passed" in review.json()

    settings_get = client.get("/api/settings")
    assert settings_get.status_code == 200
    assert "browser" in settings_get.json()

    settings_update = client.post("/api/settings", json={"browser": "firefox", "timeout_ms": 15000})
    assert settings_update.status_code == 200
    assert settings_update.json()["browser"] == "firefox"
    assert settings_update.json()["timeout_ms"] == 15000


def test_evidence_endpoint_serves_files(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    sample_dir = evidence_dir / "RUN-TEST" / "TC-001"
    sample_dir.mkdir(parents=True)
    sample_img = sample_dir / "step_1_pass.png"
    sample_img.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagecontent")

    app_settings = Settings(database_path=tmp_path / "evidence.db", uploads_dir=tmp_path / "uploads", evidence_dir=evidence_dir, scripts_dir=tmp_path / "scripts", reports_dir=tmp_path / "reports")
    client = TestClient(create_app(app_settings))
    res = client.get("/api/evidence/RUN-TEST/TC-001/step_1_pass.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content == b"\x89PNG\r\n\x1a\nfakeimagecontent"

    missing = client.get("/api/evidence/RUN-TEST/TC-001/missing.png")
    assert missing.status_code == 404