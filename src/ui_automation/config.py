from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    try:
        return int(value) if value else default
    except ValueError:
        return default


def _runtime_data_dir() -> Path:
    configured = os.getenv("DATA_DIR", "").strip()
    if configured:
        return Path(configured)
    if os.getenv("VERCEL", "").lower() == "1":
        return Path("/tmp/ui-automation")
    return ROOT_DIR / "data"


DATA_DIR = _runtime_data_dir()


@dataclass(frozen=True)
class Settings:
    database_path: Path = DATA_DIR / "automation.db"
    uploads_dir: Path = DATA_DIR / "uploaded_documents"
    evidence_dir: Path = DATA_DIR / "evidence"
    scripts_dir: Path = DATA_DIR / "generated_scripts"
    reports_dir: Path = DATA_DIR / "reports"
    skills_dir: Path = ROOT_DIR / "skills"
    llm_provider: str = os.getenv(
        "LLM_PROVIDER",
        "gemini" if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) else "openai_compatible"
    )
    llm_base_url: str = os.getenv(
        "LLM_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta"
        if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("LLM_PROVIDER") in {"gemini", "google"})
        else "https://api.openai.com/v1"
    )
    llm_model: str = os.getenv(
        "LLM_MODEL",
        "gemini-2.5-flash"
        if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("LLM_PROVIDER") in {"gemini", "google"})
        else ""
    )
    llm_api_key: str = os.getenv("LLM_API_KEY", "") or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    target_url: str = os.getenv("TARGET_URL", "")
    authentication_type: str = os.getenv("AUTHENTICATION_TYPE", "")
    target_environment: str = os.getenv("TARGET_ENVIRONMENT", "")
    target_username: str = os.getenv("TARGET_USERNAME", "")
    target_password: str = os.getenv("TARGET_PASSWORD", "")
    username_label: str = os.getenv("USERNAME_FIELD_LABEL", "")
    password_label: str = os.getenv("PASSWORD_FIELD_LABEL", "")
    submit_label: str = os.getenv("LOGIN_BUTTON_LABEL", "")
    browser: str = os.getenv("BROWSER", "")
    headless: bool = os.getenv("HEADLESS", "").lower() == "true"
    browser_configured: bool = bool(os.getenv("BROWSER"))
    mode_configured: bool = bool(os.getenv("HEADLESS"))
    timeout_ms: int = _env_int("TIMEOUT_MS", 10000)
    screenshot_on_pass: bool = os.getenv("SCREENSHOT_ON_PASS", "true").lower() == "true"
    screenshot_on_failure: bool = os.getenv("SCREENSHOT_ON_FAILURE", "true").lower() == "true"

    def prepare(self) -> None:
        for path in (self.database_path.parent, self.uploads_dir, self.evidence_dir, self.scripts_dir, self.reports_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
