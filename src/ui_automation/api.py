from __future__ import annotations

import logging
import os
import re
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ui_automation.agents import PlaywrightScriptAgent, RequirementAgent, TestCaseAgent
from ui_automation.config import Settings, settings
from ui_automation.database import Database
from ui_automation.documents import extract_text
from ui_automation.executor import ExecutionService
from ui_automation.llm import LLMProvider
from ui_automation.locator_service import LocatorService
from ui_automation.repository import Repository
from ui_automation.utils import configure_logging, log_event


class TargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_url: HttpUrl
    authentication_type: str = Field(default="No Authentication", max_length=80)
    browser: str = Field(default="chromium", pattern=r"^(chromium|firefox|webkit)$")
    headless: bool = True
    username_label: str = Field(default="", max_length=160)
    password_label: str = Field(default="", max_length=160)
    submit_label: str = Field(default="", max_length=160)
    guidance: str = Field(default="", max_length=2000)


class CredentialsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class DiscoveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: TargetInput
    credentials: CredentialsInput | None = None


class ScriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=120)


class ExecutionInput(ScriptInput):
    credentials: CredentialsInput | None = None


class RequirementSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str


class AppServices:
    def __init__(self, app_settings: Settings) -> None:
        app_settings.prepare()
        self.settings = app_settings
        self.repository = Repository(Database(app_settings.database_path))
        self.logger = configure_logging(app_settings.reports_dir)

    def provider(self) -> LLMProvider:
        return LLMProvider(self.settings.llm_provider, self.settings.llm_base_url, self.settings.llm_model, self.settings.llm_api_key)


def _allowed_origins(value: str) -> list[str]:
    origins = [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
    return origins or ["http://localhost:3000"]


def _safe_upload_name(name: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(name or "document").name).strip(".")
    return cleaned[:180] or "document"


def _require_requirement(repository: Repository, requirement_id: str) -> dict[str, Any]:
    requirement = next((item for item in repository.requirements() if item["id"] == requirement_id), None)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement was not found")
    return requirement


def _require_case(repository: Repository, case_id: str) -> dict[str, Any]:
    case = next((item for item in repository.test_cases() if item["id"] == case_id), None)
    if not case:
        raise HTTPException(status_code=404, detail="Test case was not found")
    return case


def _target_for_case(repository: Repository, case: dict[str, Any]) -> dict[str, Any]:
    target = repository.requirement_target(case["requirement_id"])
    if not target:
        raise HTTPException(status_code=409, detail="Configure a target environment for this story first")
    return target


def _case_context(repository: Repository, case: dict[str, Any]) -> dict[str, Any]:
    target = _target_for_case(repository, case)
    return {**case, "target_url": target["application_url"], "browser": target["browser"], "headless": target["headless"], "authentication_type": target["authentication_type"], "username_label": target["username_label"], "password_label": target["password_label"], "submit_label": target["submit_label"]}


def _runtime_credentials(app_settings: Settings, credentials: dict[str, Any] | None) -> dict[str, str]:
    if credentials and credentials.get("username") and credentials.get("password"):
        return {"username": str(credentials["username"]), "password": str(credentials["password"])}
    if app_settings.target_username and app_settings.target_password:
        return {"username": app_settings.target_username, "password": app_settings.target_password}
    return {}


def create_app(app_settings: Settings = settings) -> FastAPI:
    services = AppServices(app_settings)
    api = FastAPI(title="Fieldnotes QA API", version="1.0.0", docs_url="/api/docs", redoc_url=None)
    api.add_middleware(CORSMiddleware, allow_origins=_allowed_origins(os.getenv("CORS_ORIGINS", "http://localhost:3000")), allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])

    @api.middleware("http")
    async def request_context(request: Request, call_next: Any) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            services.logger.exception("api_request_failed", extra={"request_id": request_id, "path": request.url.path})
            response = JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred", "request_id": request_id})
        response.headers["X-Request-ID"] = request_id
        return response

    async def authenticate(request: Request) -> None:
        configured = os.getenv("API_AUTH_TOKEN", "").strip()
        if not configured or request.url.path in {"/api/health", "/docs", "/openapi.json", "/api/docs"}:
            return
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(token, configured):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="A valid bearer token is required")

    @api.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail, "request_id": getattr(request.state, "request_id", "")})

    @api.get("/api/health", dependencies=[Depends(authenticate)])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "fieldnotes-qa-api"}

    @api.get("/api/dashboard", dependencies=[Depends(authenticate)])
    async def dashboard() -> dict[str, Any]:
        requirements = services.repository.requirements()
        cases = services.repository.test_cases()
        results = services.repository.results()
        counts: dict[str, int] = {}
        for result in results:
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        return {"requirements": len(requirements), "test_cases": len(cases), "results": len(results), "status_counts": counts, "recent_runs": services.repository.history()[:8]}

    @api.get("/api/requirements", response_model=list[RequirementSummary], dependencies=[Depends(authenticate)])
    async def requirements() -> list[dict[str, Any]]:
        return services.repository.requirements()

    @api.get("/api/requirements/{requirement_id}", dependencies=[Depends(authenticate)])
    async def requirement(requirement_id: str) -> dict[str, Any]:
        item = _require_requirement(services.repository, requirement_id)
        return {**item, "target": services.repository.requirement_target(requirement_id), "cases": [case for case in services.repository.test_cases() if case["requirement_id"] == requirement_id], "locators": services.repository.locators(requirement_id=requirement_id)}

    @api.post("/api/requirements/analyze", dependencies=[Depends(authenticate)])
    async def analyze(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        if not files or len(files) > 10:
            raise HTTPException(status_code=400, detail="Upload between one and ten requirement documents")
        extracted: list[tuple[str, str]] = []
        saved_names: list[str] = []
        for upload in files:
            content = await upload.read()
            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"{upload.filename or 'Document'} exceeds the 10 MB limit")
            safe_name = _safe_upload_name(upload.filename)
            destination = services.settings.uploads_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}-{safe_name}"
            destination.write_bytes(content)
            try:
                extracted.append((upload.filename or safe_name, extract_text(upload.filename or safe_name, content)))
            except Exception as error:
                raise HTTPException(status_code=422, detail=f"Could not read {upload.filename or safe_name}: {error}") from error
            saved_names.append(destination.name)
        try:
            analysis, application, mode = RequirementAgent(services.settings.skills_dir, services.provider()).analyze_documents(extracted)
            requirement_id = f"REQ-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
            title = analysis.get("requirement_title") or Path(files[0].filename or "requirement").stem
            safe_analysis = {key: value for key, value in analysis.items() if key not in {"username", "password", "credentials"}}
            safe_analysis["application_details"] = {key: value for key, value in application.items() if key not in {"username", "password"}}
            services.repository.save_requirement(requirement_id, title, analysis.get("user_story", ""), analysis.get("acceptance_criteria", []), safe_analysis, saved_names)
            application_url = application.get("application_url")
            if application_url:
                services.repository.save_requirement_target({"requirement_id": requirement_id, "application_url": application_url, "authentication_type": application.get("authentication_type") or "No Authentication", "browser": application.get("browser") or "chromium", "headless": application.get("execution_mode", "headless") == "headless", "username_label": application.get("username_label") or "", "password_label": application.get("password_label") or "", "submit_label": application.get("submit_label") or "", "guidance": ""})
            log_event(services.logger, "RequirementAPI", "requirement_analyzed", requirement_id=requirement_id, analysis_mode=mode)
            return {"requirement": await requirement(requirement_id), "mode": mode}
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=422, detail=f"Requirement analysis failed: {error}") from error

    @api.put("/api/requirements/{requirement_id}/target", dependencies=[Depends(authenticate)])
    async def save_target(requirement_id: str, target: TargetInput) -> dict[str, Any]:
        _require_requirement(services.repository, requirement_id)
        payload = target.model_dump(mode="json")
        payload["requirement_id"] = requirement_id
        services.repository.save_requirement_target(payload)
        return services.repository.requirement_target(requirement_id) or {}

    @api.post("/api/requirements/{requirement_id}/discover", dependencies=[Depends(authenticate)])
    async def discover(requirement_id: str, request: DiscoveryInput) -> dict[str, Any]:
        _require_requirement(services.repository, requirement_id)
        if os.getenv("EXECUTION_ENABLED", "true").lower() != "true":
            raise HTTPException(status_code=503, detail="Browser discovery is disabled for this deployment")
        target = request.target.model_dump(mode="json")
        credentials = _runtime_credentials(services.settings, request.credentials.model_dump() if request.credentials else None)
        authentication = {**target, **credentials} if credentials else target
        locators = LocatorService(services.settings).discover(str(target["application_url"]), target["browser"], authentication if target["authentication_type"] == "Username & Password" else None, target["guidance"])
        for item in locators:
            services.repository.save_locator({**item, "requirement_id": requirement_id, "test_case_id": None})
        services.repository.save_requirement_target({**target, "application_url": str(target["application_url"]), "requirement_id": requirement_id})
        return {"count": len(locators), "locators": services.repository.locators(requirement_id=requirement_id)}

    @api.post("/api/requirements/{requirement_id}/generate", dependencies=[Depends(authenticate)])
    async def generate(requirement_id: str) -> dict[str, Any]:
        item = _require_requirement(services.repository, requirement_id)
        cases, mode = TestCaseAgent(services.settings.skills_dir, services.provider()).generate(requirement_id, item["analysis"])
        for case in cases:
            services.repository.save_test_case(case)
        return {"mode": mode, "cases": cases}

    @api.post("/api/cases/{case_id}/script", dependencies=[Depends(authenticate)])
    async def script(case_id: str, request: ScriptInput) -> dict[str, Any]:
        if request.case_id != case_id:
            raise HTTPException(status_code=400, detail="Case identifiers do not match")
        case = _require_case(services.repository, case_id)
        context = _case_context(services.repository, case)
        source = PlaywrightScriptAgent(services.settings.skills_dir, services.provider()).generate(context, services.repository.locators(test_case_id=case_id, requirement_id=case["requirement_id"]))
        services.repository.save_script(case_id, source)
        return {"case_id": case_id, "source": source}

    @api.post("/api/cases/{case_id}/execute", dependencies=[Depends(authenticate)])
    async def execute(case_id: str, request: ExecutionInput) -> dict[str, Any]:
        if request.case_id != case_id:
            raise HTTPException(status_code=400, detail="Case identifiers do not match")
        if os.getenv("EXECUTION_ENABLED", "true").lower() != "true":
            raise HTTPException(status_code=503, detail="Browser execution is disabled for this deployment")
        case = _require_case(services.repository, case_id)
        context = _case_context(services.repository, case)
        run_id = f"RUN-{uuid.uuid4()}"
        services.repository.create_run(run_id, services.settings.target_environment or "API", context["browser"])
        credentials = _runtime_credentials(services.settings, request.credentials.model_dump() if request.credentials else None)
        authentication = {**context, **credentials} if credentials else context
        outcome = ExecutionService(services.settings).run_case(context, run_id, services.repository.locators(test_case_id=case_id, requirement_id=case["requirement_id"]), context["target_url"], context["browser"], authentication=authentication)
        services.repository.save_result(run_id, case_id, outcome["status"], outcome["duration"], outcome["error"], {"source": "api"}, outcome["steps"])
        services.repository.finish_run(run_id, {"status": outcome["status"], "case_id": case_id})
        return {"run_id": run_id, "outcome": outcome}

    @api.get("/api/runs", dependencies=[Depends(authenticate)])
    async def runs() -> list[dict[str, Any]]:
        return services.repository.history()

    @api.get("/api/runs/{run_id}", dependencies=[Depends(authenticate)])
    async def run(run_id: str) -> dict[str, Any]:
        history = next((item for item in services.repository.history() if item["id"] == run_id), None)
        if not history:
            raise HTTPException(status_code=404, detail="Run was not found")
        results = services.repository.results(run_id)
        return {"run": history, "results": [{**result, "steps": services.repository.step_results(result["id"])} for result in results]}

    return api


app = create_app()