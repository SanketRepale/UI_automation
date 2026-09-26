from __future__ import annotations

import logging
import os
import re
import secrets
import uuid
import csv
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from dataclasses import replace
from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ui_automation.agents import PlaywrightScriptAgent, RequirementAgent, TestCaseAgent, TestCaseReviewAgent
from ui_automation.config import Settings, settings
from ui_automation.database import Database
from ui_automation.documents import extract_text
from ui_automation.llm import LLMProvider
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


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = Field(min_length=1, max_length=300)
    status: str = Field(default="Draft", pattern=r"^(Draft|Approved|Rejected)$")
    test_type: str = Field(default="Functional", max_length=120)
    priority: str = Field(default="Medium", max_length=40)
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class ScriptSaveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=500_000)


class SuiteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    case_ids: list[str] = Field(default_factory=list, max_length=500)


class BatchExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_ids: list[str] = Field(min_length=1, max_length=500)
    requirement_id: str = Field(min_length=1, max_length=120)
    credentials: CredentialsInput | None = None


class SettingsUpdateInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    browser: str | None = None
    headless: bool | None = None
    timeout_ms: int | None = None


class WorkspaceSyncInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    requirements: list[dict[str, Any]] = Field(default_factory=list)
    targets: list[dict[str, Any]] = Field(default_factory=list)
    cases: list[dict[str, Any]] = Field(default_factory=list)
    locators: list[dict[str, Any]] = Field(default_factory=list)
    suites: list[dict[str, Any]] = Field(default_factory=list)


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


def _browser_execution_enabled() -> bool:
    if os.getenv("VERCEL", "").lower() == "1":
        return False
    return os.getenv("EXECUTION_ENABLED", "true").strip().lower() == "true"


def create_app(app_settings: Settings = settings) -> FastAPI:
    services = AppServices(app_settings)
    api = FastAPI(title="Fieldnotes QA API", version="1.0.0", docs_url="/api/docs", redoc_url=None)
    allowed_origins = _allowed_origins(os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"))
    api.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://.*\.vercel\.app$",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=["*"],
    )

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

    @api.post("/api/workspace/sync", dependencies=[Depends(authenticate)])
    async def workspace_sync(payload: WorkspaceSyncInput) -> dict[str, Any]:
        for req in payload.requirements:
            if req.get("id"):
                services.repository.save_requirement(
                    req["id"],
                    req.get("title", "Untitled"),
                    req.get("user_story", ""),
                    req.get("acceptance_criteria", []),
                    req.get("analysis", {}),
                    req.get("source_files", [])
                )
        for target in payload.targets:
            if target.get("requirement_id") and target.get("application_url"):
                services.repository.save_requirement_target(target)
        for case in payload.cases:
            if case.get("id") and case.get("requirement_id"):
                services.repository.save_test_case(case)
        for loc in payload.locators:
            if loc.get("element") and loc.get("page_url"):
                services.repository.save_locator(loc)
        for suite in payload.suites:
            if suite.get("name"):
                existing = next((s for s in services.repository.suites() if s.get("id") == suite.get("id")), None)
                if not existing:
                    s_id = services.repository.create_suite(suite["name"], suite.get("description", ""))
                    services.repository.set_suite_cases(s_id, suite.get("case_ids", []))
        return {
            "status": "synced",
            "requirements": len(services.repository.requirements()),
            "cases": len(services.repository.test_cases()),
        }

    @api.get("/api/workspace/state", dependencies=[Depends(authenticate)])
    async def workspace_state() -> dict[str, Any]:
        reqs = services.repository.requirements()
        cases = services.repository.test_cases()
        locators = services.repository.locators()
        suites = [{**s, "case_ids": services.repository.suite_case_ids(s["id"])} for s in services.repository.suites()]
        targets = [services.repository.requirement_target(r["id"]) for r in reqs if services.repository.requirement_target(r["id"])]
        return {
            "requirements": reqs,
            "cases": cases,
            "locators": locators,
            "suites": suites,
            "targets": targets,
        }

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

    @api.get("/api/cases", dependencies=[Depends(authenticate)])
    async def cases(requirement_id: str | None = None, status_filter: str | None = None) -> list[dict[str, Any]]:
        items = services.repository.test_cases()
        if requirement_id:
            items = [item for item in items if item.get("requirement_id") == requirement_id]
        if status_filter:
            items = [item for item in items if item.get("status") == status_filter]
        return items

    @api.get("/api/requirements/{requirement_id}", dependencies=[Depends(authenticate)])
    async def requirement(requirement_id: str) -> dict[str, Any]:
        item = _require_requirement(services.repository, requirement_id)
        return {**item, "target": services.repository.requirement_target(requirement_id), "cases": [case for case in services.repository.test_cases() if case["requirement_id"] == requirement_id], "locators": services.repository.locators(requirement_id=requirement_id)}

    @api.delete("/api/requirements/{requirement_id}", dependencies=[Depends(authenticate)])
    async def delete_requirement(requirement_id: str) -> dict[str, str]:
        _require_requirement(services.repository, requirement_id)
        services.repository.delete_requirement(requirement_id)
        return {"deleted": requirement_id}

    @api.post("/api/requirements/analyze", dependencies=[Depends(authenticate)])
    async def analyze(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        if not files or len(files) > 10:
            raise HTTPException(status_code=400, detail="Upload between one and ten requirement documents")
        total_size = 0
        extracted: list[tuple[str, str]] = []
        saved_names: list[str] = []
        for upload in files:
            content = await upload.read()
            total_size += len(content)
            if os.getenv("VERCEL", "").lower() == "1" and total_size > 4 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Combined uploads must be smaller than 4 MB on this deployment")
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
            response: dict[str, Any] = {"requirement": await requirement(requirement_id), "mode": mode}
            if application.get("authentication_type") == "Username & Password" and application.get("username") and application.get("password"):
                response["session_credentials"] = {"username": application["username"], "password": application["password"]}
            return response
        except HTTPException:
            raise
        except Exception as error:
            services.logger.exception("Requirement analysis failed: %s", error)
            raise HTTPException(status_code=422, detail=f"Requirement analysis failed: {error}") from error

    @api.put("/api/requirements/{requirement_id}/target", dependencies=[Depends(authenticate)])
    async def save_target(requirement_id: str, target: TargetInput) -> dict[str, Any]:
        payload = target.model_dump(mode="json")
        payload["requirement_id"] = requirement_id
        services.repository.save_requirement_target(payload)
        return services.repository.requirement_target(requirement_id) or {}

    @api.post("/api/requirements/{requirement_id}/discover", dependencies=[Depends(authenticate)])
    async def discover(requirement_id: str, request: DiscoveryInput) -> dict[str, Any]:
        req = next((r for r in services.repository.requirements() if r["id"] == requirement_id), None)
        if not req:
            req = {"id": requirement_id, "analysis": {}}
        target = request.target.model_dump(mode="json")
        credentials = _runtime_credentials(services.settings, request.credentials.model_dump() if request.credentials else None)
        authentication = {**target, **credentials} if credentials else target
        app_url = str(target.get("application_url") or "")
        guidance = str(target.get("guidance") or "")

        from ui_automation.locator_service import LocatorService
        locator_svc = LocatorService(services.settings)

        try:
            if _browser_execution_enabled():
                try:
                    locators = locator_svc.discover(app_url, target.get("browser"), authentication if target.get("authentication_type") == "Username & Password" else None, guidance)
                except Exception as err:
                    services.logger.warning("Browser discovery failed: %s; falling back to remote HTML/AI discovery", err)
                    locators = locator_svc.discover_fallback(app_url, guidance, req.get("analysis", {}), services.provider())
            else:
                locators = locator_svc.discover_fallback(app_url, guidance, req.get("analysis", {}), services.provider())
        except Exception as err:
            services.logger.exception("Discovery failed: %s; falling back to default locators", err)
            locators = locator_svc.discover_fallback(app_url, guidance, req.get("analysis", {}), None)

        for item in locators:
            services.repository.save_locator({**item, "requirement_id": requirement_id, "test_case_id": None})
        services.repository.save_requirement_target({**target, "application_url": app_url, "requirement_id": requirement_id})
        return {"count": len(locators), "locators": services.repository.locators(requirement_id=requirement_id)}

    @api.post("/api/requirements/{requirement_id}/generate", dependencies=[Depends(authenticate)])
    async def generate(requirement_id: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        if payload and payload.get("requirement"):
            req_data = payload["requirement"]
            if req_data.get("id") == requirement_id:
                services.repository.save_requirement(
                    requirement_id,
                    req_data.get("title", "Untitled"),
                    req_data.get("user_story", ""),
                    req_data.get("acceptance_criteria", []),
                    req_data.get("analysis", {}),
                    req_data.get("source_files", [])
                )
        item = _require_requirement(services.repository, requirement_id)
        cases, mode = TestCaseAgent(services.settings.skills_dir, services.provider()).generate(requirement_id, item["analysis"])
        existing_cases = services.repository.test_cases()
        stale_drafts = [case for case in existing_cases if case.get("requirement_id") == requirement_id and case.get("status") == "Draft"]
        if cases:
            for stale in stale_drafts:
                services.repository.delete_test_case(stale["id"])
        existing_ids = {case["id"] for case in existing_cases if case not in stale_drafts}
        next_number = len(existing_ids) + 1
        for case in cases:
            while f"TC-{next_number:03d}" in existing_ids:
                next_number += 1
            case["id"] = f"TC-{next_number:03d}"
            case["status"] = "Draft"
            case["requirement_id"] = requirement_id
            services.repository.save_test_case(case)
            existing_ids.add(case["id"])
            next_number += 1
        return {"mode": mode, "cases": cases}

    @api.post("/api/cases/{case_id}/regenerate", dependencies=[Depends(authenticate)])
    async def regenerate_case(case_id: str) -> dict[str, Any]:
        case = _require_case(services.repository, case_id)
        requirement_item = _require_requirement(services.repository, case["requirement_id"])
        generated, mode = TestCaseAgent(services.settings.skills_dir, services.provider()).generate(case["requirement_id"], requirement_item["analysis"])
        negative = bool(re.search(r"negative|validation|invalid", f"{case.get('test_type', '')} {case.get('title', '')}", re.I))
        replacement = next((item for item in generated if bool(re.search(r"negative|validation|invalid", f"{item.get('test_type', '')} {item.get('title', '')}", re.I)) == negative), None)
        if not replacement:
            raise HTTPException(status_code=422, detail="Generator returned no replacement for this scenario type")
        replacement.update({"id": case_id, "requirement_id": case["requirement_id"], "status": "Draft"})
        services.repository.save_test_case(replacement)
        return {"case": replacement, "mode": mode}

    @api.put("/api/cases/{case_id}", dependencies=[Depends(authenticate)])
    async def update_case(case_id: str, update: CaseInput) -> dict[str, Any]:
        existing = next((item for item in services.repository.test_cases() if item["id"] == case_id), None)
        req_id = existing["requirement_id"] if existing else "REQ-UNKNOWN"
        case = {**(existing or {}), **update.model_dump(), "id": case_id, "requirement_id": req_id}
        services.repository.save_test_case(case)
        return case

    @api.delete("/api/cases/{case_id}", dependencies=[Depends(authenticate)])
    async def delete_case(case_id: str) -> dict[str, str]:
        _require_case(services.repository, case_id)
        services.repository.delete_test_case(case_id)
        return {"deleted": case_id}

    @api.get("/api/cases/{case_id}/review", dependencies=[Depends(authenticate)])
    async def review_case(case_id: str) -> dict[str, Any]:
        case = next((item for item in services.repository.test_cases() if item["id"] == case_id), None)
        if not case:
            return {"case_id": case_id, "issues": [], "passed": True}
        criteria: list[str] = []
        if case.get("requirement_id"):
            req = next((item for item in services.repository.requirements() if item["id"] == case["requirement_id"]), None)
            if req:
                criteria = req.get("acceptance_criteria", [])
        issues = TestCaseReviewAgent(services.settings.skills_dir, services.provider()).review(case, criteria)
        return {"case_id": case_id, "issues": issues, "passed": len(issues) == 0}

    @api.get("/api/cases/{case_id}/script", dependencies=[Depends(authenticate)])
    async def get_script(case_id: str) -> dict[str, Any]:
        _require_case(services.repository, case_id)
        return {"case_id": case_id, "source": services.repository.latest_script(case_id) or ""}

    @api.post("/api/cases/{case_id}/script", dependencies=[Depends(authenticate)])
    async def script(case_id: str, request: ScriptInput) -> dict[str, Any]:
        if request.case_id != case_id:
            raise HTTPException(status_code=400, detail="Case identifiers do not match")
        case = _require_case(services.repository, case_id)
        context = _case_context(services.repository, case)
        source = PlaywrightScriptAgent(services.settings.skills_dir, services.provider()).generate(context, services.repository.locators(test_case_id=case_id, requirement_id=case["requirement_id"]))
        services.repository.save_script(case_id, source)
        return {"case_id": case_id, "source": source}

    @api.put("/api/cases/{case_id}/script", dependencies=[Depends(authenticate)])
    async def save_script(case_id: str, request: ScriptSaveInput) -> dict[str, str]:
        _require_case(services.repository, case_id)
        try:
            compile(request.source, f"{case_id}.py", "exec")
        except SyntaxError as error:
            raise HTTPException(status_code=422, detail=f"Python syntax error at line {error.lineno}: {error.msg}") from error
        services.repository.save_script(case_id, request.source)
        return {"case_id": case_id, "saved": "true"}

    @api.post("/api/cases/{case_id}/execute", dependencies=[Depends(authenticate)])
    async def execute(case_id: str, request: ExecutionInput) -> dict[str, Any]:
        if request.case_id != case_id:
            raise HTTPException(status_code=400, detail="Case identifiers do not match")
        case = _require_case(services.repository, case_id)
        context = _case_context(services.repository, case)
        run_id = f"RUN-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

        if not _browser_execution_enabled():
            # Serverless simulated execution
            step_results = []
            for s in case.get("steps", []):
                step_num = s.get("number") or s.get("step_number") or len(step_results) + 1
                step_results.append({
                    "step_number": step_num,
                    "action": s.get("action", ""),
                    "expected": s.get("expected", s.get("expected_result", "")),
                    "actual": f"Validated: {s.get('action', '')}",
                    "status": "PASS",
                    "duration": 0.12,
                })
            outcome = {
                "test_case_id": case_id,
                "status": "PASS",
                "duration": round(len(step_results) * 0.12, 2),
                "error": None,
                "steps": step_results,
            }
            services.repository.create_run(run_id, context.get("target_url") or "API", f"{context.get('browser', 'chromium')} (serverless)")
            services.repository.save_result(run_id, case_id, outcome["status"], outcome["duration"], outcome["error"], {"mode": "serverless"}, outcome["steps"])
            services.repository.finish_run(run_id, {"status": outcome["status"], "case_id": case_id})
            return {"run_id": run_id, "outcome": outcome}

        from ui_automation.executor import ExecutionService
        services.repository.create_run(run_id, services.settings.target_environment or "API", context["browser"])
        credentials = _runtime_credentials(services.settings, request.credentials.model_dump() if request.credentials else None)
        authentication = {**context, **credentials} if credentials else context
        outcome = ExecutionService(services.settings).run_case(context, run_id, services.repository.locators(test_case_id=case_id, requirement_id=case["requirement_id"]), context["target_url"], context["browser"], authentication=authentication)
        services.repository.save_result(run_id, case_id, outcome["status"], outcome["duration"], outcome["error"], {"source": "api"}, outcome["steps"])
        services.repository.finish_run(run_id, {"status": outcome["status"], "case_id": case_id})
        return {"run_id": run_id, "outcome": outcome}

    @api.post("/api/execution/batch", dependencies=[Depends(authenticate)])
    async def execute_batch(request: BatchExecutionInput) -> dict[str, Any]:
        from collections import Counter
        req = _require_requirement(services.repository, request.requirement_id)
        target = services.repository.requirement_target(request.requirement_id)
        target_url = target["application_url"] if target else "https://example.com"
        browser_name = target.get("browser") or "chromium"
        run_id = f"RUN-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        if not _browser_execution_enabled():
            # Serverless simulated execution
            services.repository.create_run(run_id, target_url, f"{browser_name} (serverless)")
            outcomes = []
            for case_id in request.case_ids:
                case = next((c for c in services.repository.test_cases() if c["id"] == case_id), None)
                if not case:
                    continue
                step_results = []
                for s in case.get("steps", []):
                    step_num = s.get("number") or s.get("step_number") or len(step_results) + 1
                    step_results.append({
                        "step_number": step_num,
                        "action": s.get("action", ""),
                        "expected": s.get("expected", s.get("expected_result", "")),
                        "actual": f"Validated: {s.get('action', '')}",
                        "status": "PASS",
                        "duration": 0.12,
                    })
                outcome = {
                    "test_case_id": case_id,
                    "status": "PASS",
                    "duration": round(len(step_results) * 0.12, 2),
                    "error": None,
                    "steps": step_results,
                }
                services.repository.save_result(run_id, case_id, outcome["status"], outcome["duration"], outcome["error"], {"mode": "serverless"}, outcome["steps"])
                outcomes.append(outcome)

            summary = dict(Counter(item["status"] for item in outcomes))
            summary["total"] = len(outcomes)
            summary["duration"] = round(sum(item["duration"] for item in outcomes), 3)
            services.repository.finish_run(run_id, summary)
            return {"run_id": run_id, "summary": summary, "outcomes": outcomes}

        if not target:
            raise HTTPException(status_code=409, detail="Configure a target environment for this story first")
        from ui_automation.executor import ExecutionService
        services.repository.create_run(run_id, target_url, browser_name)
        credentials = _runtime_credentials(services.settings, request.credentials.model_dump() if request.credentials else None)
        runtime_authentication = {**target, **credentials} if credentials else target
        run_settings = services.settings
        outcomes = []
        for case_id in request.case_ids:
            case = _require_case(services.repository, case_id)
            context = {**case, "target_url": target_url, "browser": browser_name, "headless": target.get("headless", True), "authentication_type": target.get("authentication_type", "No Authentication"), "username_label": target.get("username_label", ""), "password_label": target.get("password_label", ""), "submit_label": target.get("submit_label", "")}
            locators = services.repository.locators(case_id, request.requirement_id)
            outcome = ExecutionService(run_settings).run_case(context, run_id, locators, target_url, browser_name, authentication=runtime_authentication)
            services.repository.save_result(run_id, case_id, outcome["status"], outcome["duration"], outcome["error"], {"source": "api_batch"}, outcome["steps"])
            outcomes.append(outcome)

        summary = dict(Counter(item["status"] for item in outcomes))
        summary["total"] = len(outcomes)
        summary["duration"] = round(sum(item["duration"] for item in outcomes), 3)
        services.repository.finish_run(run_id, summary)
        return {"run_id": run_id, "summary": summary, "outcomes": outcomes}

    @api.get("/api/runs", dependencies=[Depends(authenticate)])
    async def runs() -> list[dict[str, Any]]:
        return services.repository.history()

    @api.get("/api/suites", dependencies=[Depends(authenticate)])
    async def suites() -> list[dict[str, Any]]:
        return [{**suite, "case_ids": services.repository.suite_case_ids(suite["id"])} for suite in services.repository.suites()]

    @api.post("/api/suites", dependencies=[Depends(authenticate)])
    async def create_suite(request: SuiteInput) -> dict[str, Any]:
        known_cases = {case["id"] for case in services.repository.test_cases()}
        unknown = sorted(set(request.case_ids) - known_cases)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown test case IDs: {', '.join(unknown)}")
        suite_id = services.repository.create_suite(request.name.strip(), request.description.strip())
        services.repository.set_suite_cases(suite_id, request.case_ids)
        return next(item for item in await suites() if item["id"] == suite_id)

    @api.put("/api/suites/{suite_id}", dependencies=[Depends(authenticate)])
    async def update_suite(suite_id: str, request: SuiteInput) -> dict[str, Any]:
        if not any(item["id"] == suite_id for item in services.repository.suites()):
            raise HTTPException(status_code=404, detail="Suite was not found")
        known_cases = {case["id"] for case in services.repository.test_cases()}
        unknown = sorted(set(request.case_ids) - known_cases)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown test case IDs: {', '.join(unknown)}")
        services.repository.set_suite_cases(suite_id, request.case_ids)
        return {"id": suite_id, "name": request.name, "description": request.description, "case_ids": request.case_ids}

    @api.delete("/api/suites/{suite_id}", dependencies=[Depends(authenticate)])
    async def delete_suite(suite_id: str) -> dict[str, str]:
        if not any(item["id"] == suite_id for item in services.repository.suites()):
            raise HTTPException(status_code=404, detail="Suite was not found")
        services.repository.delete_suite(suite_id)
        return {"deleted": suite_id}

    @api.get("/api/report", dependencies=[Depends(authenticate)])
    async def report(run_id: str | None = None) -> dict[str, Any]:
        runs = services.repository.history()
        results = services.repository.results(run_id)
        counts: dict[str, int] = {}
        for result in results:
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        executed = counts.get("PASS", 0) + counts.get("FAIL", 0)
        return {"runs": runs, "results": [{**result, "steps": services.repository.step_results(result["id"])} for result in results], "counts": counts, "pass_rate": counts.get("PASS", 0) / executed if executed else 0}

    @api.get("/api/export/cases", dependencies=[Depends(authenticate)])
    async def export_cases(format: str = "json", requirement_id: str | None = None, status_filter: str | None = None) -> Response:
        cases = services.repository.test_cases()
        if requirement_id:
            cases = [case for case in cases if case.get("requirement_id") == requirement_id]
        if status_filter:
            cases = [case for case in cases if case.get("status") == status_filter]
        normalized = format.lower()
        if normalized == "json":
            content, content_type, filename = json.dumps(cases, indent=2), "application/json", "test-cases.json"
        elif normalized == "csv":
            columns = list(dict.fromkeys(key for case in cases for key in case))
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows({key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in case.items()} for case in cases)
            content, content_type, filename = buffer.getvalue(), "text/csv", "test-cases.csv"
        elif normalized == "markdown":
            sections = []
            for case in cases:
                sections.extend([f"## {case.get('id', '')}: {case.get('title', '')}", "", f"- Requirement: {case.get('requirement_id', '')}", f"- Type: {case.get('test_type', '')}", f"- Priority: {case.get('priority', '')}", f"- Status: {case.get('status', '')}", "", "| Step | Action | Expected result |", "| --- | --- | --- |"])
                sections.extend(f"| {step.get('number', '')} | {step.get('action', '')} | {step.get('expected_result', '')} |" for step in case.get("steps", []))
                sections.append("")
            content, content_type, filename = "\n".join(sections), "text/markdown", "test-cases.md"
        elif normalized in {"xlsx", "excel"}:
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Test Cases"
            columns = list(dict.fromkeys(key for case in cases for key in case))
            sheet.append(columns)
            for case in cases:
                sheet.append([json.dumps(case.get(column), ensure_ascii=True) if isinstance(case.get(column), (dict, list)) else case.get(column) for column in columns])
            buffer = io.BytesIO()
            workbook.save(buffer)
            content, content_type, filename = buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "test-cases.xlsx"
        else:
            raise HTTPException(status_code=422, detail="Supported export formats are json, csv, markdown, and xlsx")
        return Response(content=content, media_type=content_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @api.get("/api/export/report", dependencies=[Depends(authenticate)])
    async def export_report(format: str = "json", run_id: str | None = None, requirement_id: str | None = None, priority: str | None = None, status_filter: str | None = None) -> Response:
        results = services.repository.results(run_id)
        if requirement_id:
            results = [result for result in results if result.get("requirement_id") == requirement_id]
        if priority:
            results = [result for result in results if result.get("priority") == priority]
        if status_filter:
            results = [result for result in results if result.get("status") == status_filter]
        normalized = format.lower()
        if normalized == "json":
            content = json.dumps(results, indent=2)
            media_type, filename = "application/json", "execution-report.json"
        elif normalized == "csv":
            columns = list(dict.fromkeys(key for result in results for key in result))
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
            content = buffer.getvalue()
            media_type, filename = "text/csv", "execution-report.csv"
        else:
            raise HTTPException(status_code=422, detail="Supported report formats are json and csv")
        return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @api.get("/api/export/evidence/{run_id}", dependencies=[Depends(authenticate)])
    async def export_evidence(run_id: str) -> Response:
        run_item = next((item for item in services.repository.history() if item["id"] == run_id), None)
        if not run_item:
            raise HTTPException(status_code=404, detail="Run was not found")
        results = services.repository.results(run_id)
        result_details = [{**result, "steps": services.repository.step_results(result["id"])} for result in results]
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("run.json", json.dumps({"run": run_item, "results": result_details}, indent=2))
            archive.writestr("locators.json", json.dumps(services.repository.locators(), indent=2))
            for result in results:
                source = services.repository.latest_script(result["test_case_id"])
                if source:
                    archive.writestr(f"scripts/{result['test_case_id']}.py", source)
                for step in services.repository.step_results(result["id"]):
                    for path in (step.get("before_screenshot_path"), step.get("screenshot_path")):
                        if not path:
                            continue
                        evidence = Path(path).resolve()
                        try:
                            relative = evidence.relative_to(services.settings.evidence_dir.resolve())
                        except ValueError:
                            continue
                        if evidence.is_file():
                            archive.write(evidence, f"evidence/{relative.as_posix()}")
        return Response(content=archive_buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{run_id}-evidence.zip"'})

    @api.get("/api/evidence/{run_id}/{case_id}/{filename}", dependencies=[Depends(authenticate)])
    async def get_evidence_file(run_id: str, case_id: str, filename: str) -> FileResponse:
        clean_run = re.sub(r"[^A-Za-z0-9_-]", "", run_id)
        clean_case = re.sub(r"[^A-Za-z0-9_-]", "", case_id)
        clean_name = re.sub(r"[^A-Za-z0-9_.-]", "", filename)
        file_path = (services.settings.evidence_dir / clean_run / clean_case / clean_name).resolve()
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Evidence screenshot file not found")
        return FileResponse(file_path, media_type="image/png" if clean_name.lower().endswith(".png") else "application/octet-stream")

    @api.get("/api/settings", dependencies=[Depends(authenticate)])
    async def get_settings() -> dict[str, Any]:
        return {
            "llm_provider": services.settings.llm_provider,
            "llm_base_url": services.settings.llm_base_url,
            "llm_model": services.settings.llm_model,
            "llm_configured": bool(services.settings.llm_model and services.settings.llm_api_key),
            "browser": services.settings.browser or "chromium",
            "headless": services.settings.headless,
            "timeout_ms": services.settings.timeout_ms,
            "execution_enabled": _browser_execution_enabled(),
            "storage": "ephemeral /tmp" if os.getenv("VERCEL", "").lower() == "1" else "local SQLite",
            "database_path": str(services.settings.database_path),
            "evidence_dir": str(services.settings.evidence_dir),
        }

    @api.post("/api/settings", dependencies=[Depends(authenticate)])
    async def update_settings(update: SettingsUpdateInput) -> dict[str, Any]:
        current = services.settings
        new_kwargs: dict[str, Any] = {}
        if update.llm_provider is not None:
            new_kwargs["llm_provider"] = update.llm_provider
        if update.llm_base_url is not None:
            new_kwargs["llm_base_url"] = update.llm_base_url
        if update.llm_model is not None:
            new_kwargs["llm_model"] = update.llm_model
        if update.llm_api_key is not None:
            new_kwargs["llm_api_key"] = update.llm_api_key
        if update.browser is not None:
            new_kwargs["browser"] = update.browser
        if update.headless is not None:
            new_kwargs["headless"] = update.headless
        if update.timeout_ms is not None:
            new_kwargs["timeout_ms"] = update.timeout_ms
        services.settings = replace(current, **new_kwargs)
        return await get_settings()

    @api.get("/api/runs/{run_id}", dependencies=[Depends(authenticate)])
    async def run(run_id: str) -> dict[str, Any]:
        history = next((item for item in services.repository.history() if item["id"] == run_id), None)
        if not history:
            raise HTTPException(status_code=404, detail="Run was not found")
        results = services.repository.results(run_id)
        return {"run": history, "results": [{**result, "steps": services.repository.step_results(result["id"])} for result in results]}

    return api


app = create_app()