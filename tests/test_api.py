from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ui_automation.api import create_app
from ui_automation.config import Settings, _env_int, _runtime_data_dir


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


def test_api_rejects_invalid_target_url(tmp_path: Path) -> None:
    app_settings = Settings(database_path=tmp_path / "api.db", uploads_dir=tmp_path / "uploads", evidence_dir=tmp_path / "evidence", scripts_dir=tmp_path / "scripts", reports_dir=tmp_path / "reports")
    client = TestClient(create_app(app_settings))
    response = client.put("/api/requirements/missing/target", json={"application_url": "not-a-url"})
    assert response.status_code == 422