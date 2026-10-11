from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Data directory
    data_dir: Annotated[Path, Field(default=ROOT_DIR / "data")] = ROOT_DIR / "data"

    # Database
    database_path: Path = ROOT_DIR / "data" / "automation.db"

    # Directories
    uploads_dir: Path = ROOT_DIR / "data" / "uploaded_documents"
    evidence_dir: Path = ROOT_DIR / "data" / "evidence"
    scripts_dir: Path = ROOT_DIR / "data" / "generated_scripts"
    reports_dir: Path = ROOT_DIR / "data" / "reports"
    skills_dir: Path = ROOT_DIR / "skills"

    # LLM
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    llm_api_key: str = ""

    # Target application
    target_url: str = ""
    authentication_type: str = "No Authentication"
    target_environment: str = ""
    target_username: str = ""
    target_password: str = ""
    username_label: str = ""
    password_label: str = ""
    submit_label: str = ""

    # Browser
    browser: str = "chromium"
    headless: bool = True
    browser_configured: bool = False
    mode_configured: bool = False
    timeout_ms: int = 10000
    screenshot_on_pass: bool = True
    screenshot_on_failure: bool = True

    # Security
    api_auth_token: str = ""
    cors_origins: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"
    execution_enabled: bool = True
    environment: str = "development"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._resolve_data_dir()
        self._resolve_llm_defaults()
        self._resolve_browser_flags()

    def _resolve_data_dir(self) -> None:
        # Only auto-resolve if using default paths (not explicitly provided in kwargs)
        if os.getenv("VERCEL", "").lower() == "1":
            self.data_dir = Path("/tmp/ui-automation")
        elif self.data_dir == ROOT_DIR / "data" and os.getenv("DATA_DIR"):
            self.data_dir = Path(os.getenv("DATA_DIR", ""))

        # Only recompute dependent paths if they still have default values
        if self.database_path == ROOT_DIR / "data" / "automation.db":
            self.database_path = self.data_dir / "automation.db"
        if self.uploads_dir == ROOT_DIR / "data" / "uploaded_documents":
            self.uploads_dir = self.data_dir / "uploaded_documents"
        if self.evidence_dir == ROOT_DIR / "data" / "evidence":
            self.evidence_dir = self.data_dir / "evidence"
        if self.scripts_dir == ROOT_DIR / "data" / "generated_scripts":
            self.scripts_dir = self.data_dir / "generated_scripts"
        if self.reports_dir == ROOT_DIR / "data" / "reports":
            self.reports_dir = self.data_dir / "reports"

    def _resolve_llm_defaults(self) -> None:
        has_gemini = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        if has_gemini and not self.llm_api_key:
            self.llm_api_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        if has_gemini and self.llm_provider == "openai_compatible":
            self.llm_provider = "gemini"
            self.llm_base_url = "https://generativelanguage.googleapis.com/v1beta"
            if not self.llm_model:
                self.llm_model = "gemini-3.7-flash"

    def _resolve_browser_flags(self) -> None:
        self.browser_configured = bool(os.getenv("BROWSER"))
        self.mode_configured = bool(os.getenv("HEADLESS"))

    def _env_int(self, name: str, default: int) -> int:
        value = os.getenv(name, "").strip()
        try:
            return int(value) if value else default
        except ValueError:
            return default

    def _runtime_data_dir(self) -> Path:
        configured = os.getenv("DATA_DIR", "").strip()
        if configured:
            return Path(configured)
        if os.getenv("VERCEL", "").lower() == "1":
            return Path("/tmp/ui-automation")
        return ROOT_DIR / "data"

    def prepare(self) -> None:
        for path in (self.database_path.parent, self.uploads_dir, self.evidence_dir, self.scripts_dir, self.reports_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()


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


def _browser_execution_enabled() -> bool:
    """Backward-compatible wrapper using global settings."""
    if os.getenv("VERCEL", "").lower() == "1":
        return False
    return settings.execution_enabled