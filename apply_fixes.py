"""
Apply production-grade fixes to api.py carefully.
"""
import re

content = open('src/ui_automation/api.py').read()

# 1. Fix CORS: restrict allow_headers, add _is_production check for allow_origin_regex
old_cors = '''    allowed_origins = _allowed_origins(os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"))
    api.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://.*\.vercel\.app$",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=["*"],
    )'''

new_cors = '''    allowed_origins = _allowed_origins(os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"))
    allow_origin_regex = None if _is_production(app_settings) else r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://.*\.vercel\.app$"
    api.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=allow_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )'''

content = content.replace(old_cors, new_cors)

# 2. Fix error handler to not leak details in production
old_error = '''        except Exception as error:
            services.logger.exception("api_request_failed", extra={"request_id": request_id, "path": request.url.path})
            response = JSONResponse(status_code=500, content={"detail": f"An unexpected server error occurred: {error}", "request_id": request_id})'''

new_error = '''        except Exception as error:
            services.logger.exception("api_request_failed", extra={"request_id": request_id, "path": request.url.path})
            detail = "An unexpected server error occurred" if _is_production(app_settings) else f"An unexpected server error occurred: {error}"
            response = JSONResponse(status_code=500, content={"detail": detail, "request_id": request_id})'''

content = content.replace(old_error, new_error)

# 3. Fix simulated execution in execute endpoint - return SIMULATED instead of PASS
old_execute_sim = '''        if not _browser_execution_enabled():
            # Serverless simulated execution -- build context safely without requiring a target
            target = services.repository.requirement_target(case["requirement_id"])
            target_url = target["application_url"] if target else "https://example.com"
            browser_label = (target.get("browser") if target else "chromium") or "chromium"
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
                "error": "",
                "steps": step_results,
            }
            services.repository.create_run(run_id, target_url, f"{browser_label} (serverless)")
            services.repository.save_result(run_id, case_id, outcome["status"], outcome["duration"], outcome["error"], {"mode": "serverless"}, outcome["steps"])
            services.repository.finish_run(run_id, {"status": outcome["status"], "case_id": case_id})
            return {"run_id": run_id, "outcome": outcome}'''

new_execute_sim = '''        if not _browser_execution_enabled(app_settings):
            # Serverless simulated execution -- build context safely without requiring a target
            target = services.repository.requirement_target(case["requirement_id"])
            target_url = target["application_url"] if target else "https://example.com"
            browser_label = (target.get("browser") if target else "chromium") or "chromium"
            step_results = []
            for s in case.get("steps", []):
                step_num = s.get("number") or s.get("step_number") or len(step_results) + 1
                step_results.append({
                    "step_number": step_num,
                    "action": s.get("action", ""),
                    "expected": s.get("expected", s.get("expected_result", "")),
                    "actual": "Serverless mode -- no browser execution. Step not verified.",
                    "status": "SIMULATED",
                    "duration": 0.0,
                })
            outcome = {
                "test_case_id": case_id,
                "status": "SIMULATED",
                "duration": 0.0,
                "error": "Browser execution disabled (EXECUTION_ENABLED=false or VERCEL=1). Run on a worker with Playwright for real results.",
                "steps": step_results,
            }
            services.repository.create_run(run_id, target_url, f"{browser_label} (serverless)")
            services.repository.save_result(run_id, case_id, outcome["status"], outcome["duration"], outcome["error"], {"mode": "serverless"}, outcome["steps"])
            services.repository.finish_run(run_id, {"status": outcome["status"], "case_id": case_id})
            return {"run_id": run_id, "outcome": outcome}'''

content = content.replace(old_execute_sim, new_execute_sim)

# 4. Fix simulated execution in batch endpoint
old_batch_sim = '''        if not _browser_execution_enabled():
            # Serverless simulated execution
            if request.requirement_id and not any(r["id"] == request.requirement_id for r in services.repository.requirements()):
                try:
                    services.repository.save_requirement(request.requirement_id, "Active Requirement", "", [], {}, [])
                except Exception:
                    pass
            services.repository.create_run(run_id, target_url, f"{browser_name} (serverless)")
            cases_pool: dict[str, Any] = {c["id"]: c for c in services.repository.test_cases()}
            if request.cases:
                for c in request.cases:
                    if isinstance(c, dict) and c.get("id"):
                        cases_pool[c["id"]] = c
                        try:
                            services.repository.save_test_case(c)
                        except Exception:
                            pass

            outcomes = []
            for case_id in request.case_ids:
                case = cases_pool.get(case_id)
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
                    "error": "",
                    "steps": step_results,
                }
                services.repository.save_result(run_id, case_id, outcome["status"], outcome["duration"], outcome["error"], {"mode": "serverless"}, outcome["steps"])
                outcomes.append(outcome)

            summary = dict(Counter(item["status"] for item in outcomes))
            summary["total"] = len(outcomes)
            summary["duration"] = round(sum(item["duration"] for item in outcomes), 3)
            services.repository.finish_run(run_id, summary)
            return {"run_id": run_id, "summary": summary, "outcomes": outcomes}'''

new_batch_sim = '''        if not _browser_execution_enabled(app_settings):
            # Serverless simulated execution
            if request.requirement_id and not any(r["id"] == request.requirement_id for r in services.repository.requirements()):
                try:
                    services.repository.save_requirement(request.requirement_id, "Active Requirement", "", [], {}, [])
                except Exception:
                    pass
            services.repository.create_run(run_id, target_url, f"{browser_name} (serverless)")
            cases_pool: dict[str, Any] = {c["id"]: c for c in services.repository.test_cases()}
            if request.cases:
                for c in request.cases:
                    if isinstance(c, dict) and c.get("id"):
                        cases_pool[c["id"]] = c
                        try:
                            services.repository.save_test_case(c)
                        except Exception:
                            pass

            outcomes = []
            for case_id in request.case_ids:
                case = cases_pool.get(case_id)
                if not case:
                    continue
                step_results = []
                for s in case.get("steps", []):
                    step_num = s.get("number") or s.get("step_number") or len(step_results) + 1
                    step_results.append({
                        "step_number": step_num,
                        "action": s.get("action", ""),
                        "expected": s.get("expected", s.get("expected_result", "")),
                        "actual": "Serverless mode -- no browser execution. Step not verified.",
                        "status": "SIMULATED",
                        "duration": 0.0,
                    })
                outcome = {
                    "test_case_id": case_id,
                    "status": "SIMULATED",
                    "duration": 0.0,
                    "error": "Browser execution disabled (EXECUTION_ENABLED=false or VERCEL=1). Run on a worker with Playwright for real results.",
                    "steps": step_results,
                }
                services.repository.save_result(run_id, case_id, outcome["status"], outcome["duration"], outcome["error"], {"mode": "serverless"}, outcome["steps"])
                outcomes.append(outcome)

            summary = dict(Counter(item["status"] for item in outcomes))
            summary["total"] = len(outcomes)
            summary["duration"] = 0.0
            services.repository.finish_run(run_id, summary)
            return {"run_id": run_id, "summary": summary, "outcomes": outcomes}'''

content = content.replace(old_batch_sim, new_batch_sim)

# 5. Remove session_credentials from analyze response
old_analyze_creds = '''            log_event(services.logger, "RequirementAPI", "requirement_analyzed", requirement_id=requirement_id, analysis_mode=mode)
            response: dict[str, Any] = {"requirement": await requirement(requirement_id), "mode": mode}
            if application.get("authentication_type") == "Username & Password" and application.get("username") and application.get("password"):
                response["session_credentials"] = {"username": application["username"], "password": application["password"]}
            return response'''

new_analyze_creds = '''            log_event(services.logger, "RequirementAPI", "requirement_analyzed", requirement_id=requirement_id, analysis_mode=mode)
            response: dict[str, Any] = {"requirement": await requirement(requirement_id), "mode": mode}
            # Credentials are NOT returned in API response for security.
            # Frontend must collect credentials from user and send with discover/execute requests.
            return response'''

content = content.replace(old_analyze_creds, new_analyze_creds)

# 6. Fix heuristic locators in discover endpoint - validated=False, confidence=0.10
old_heuristic = '''            for d in heuristic_defaults:
                locators.append({
                    "element": d["element"], "tag": d["tag"], "xpath": d["xpath"],
                    "candidates": [{"kind": "xpath", "value": d["xpath"], "valid": True, "count": 1}],
                    "selected": d["xpath"], "validated": True, "confidence": 0.70,
                    "guidance_matches": [], "page_url": app_url,
                    "last_validated": now_iso, "explanation": "Heuristic default (Playwright unavailable).",
                })'''

new_heuristic = '''            for d in heuristic_defaults:
                locators.append({
                    "element": d["element"], "tag": d["tag"], "xpath": d["xpath"],
                    "candidates": [{"kind": "xpath", "value": d["xpath"], "valid": False, "count": 0, "reason": "heuristic only"}],
                    "selected": d["xpath"], "validated": False, "confidence": 0.10,
                    "guidance_matches": [], "page_url": app_url,
                    "last_validated": now_iso, "explanation": "Heuristic default (Playwright unavailable) -- NOT validated.",
                })'''

content = content.replace(old_heuristic, new_heuristic)

# 7. Update _is_production to use app_settings
old_is_prod = '''def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development").lower() == "production"'''

new_is_prod = '''def _is_production(app_settings: Settings) -> bool:
    return app_settings.environment.lower() == "production"'''

content = content.replace(old_is_prod, new_is_prod)

# 8. Update _browser_execution_enabled to use app_settings and add legacy wrapper
old_browser_exec = '''def _browser_execution_enabled() -> bool:
    if os.getenv("VERCEL", "").lower() == "1":
        return False
    return os.getenv("EXECUTION_ENABLED", "true").strip().lower() == "true"'''

new_browser_exec = '''def _browser_execution_enabled(app_settings: Settings) -> bool:
    if os.getenv("VERCEL", "").lower() == "1":
        return False
    return app_settings.execution_enabled


def _browser_execution_enabled_legacy() -> bool:
    """Backward-compatible wrapper using global settings."""
    if os.getenv("VERCEL", "").lower() == "1":
        return False
    return settings.execution_enabled'''

content = content.replace(old_browser_exec, new_browser_exec)

# 9. Fix all calls to _browser_execution_enabled() to pass app_settings
content = content.replace('if not _browser_execution_enabled():', 'if not _browser_execution_enabled(app_settings):')
content = content.replace('if locator_svc is not None and _browser_execution_enabled():', 'if locator_svc is not None and _browser_execution_enabled(app_settings):')
content = content.replace('"execution_enabled": _browser_execution_enabled(),', '"execution_enabled": _browser_execution_enabled(app_settings),')

# 10. Update _runtime_credentials to use app_settings (already uses it, but _is_production calls need fixing)
# The calls to _is_production() in create_app need to pass app_settings
content = content.replace('allow_origin_regex = None if _is_production() else', 'allow_origin_regex = None if _is_production(app_settings) else')
content = content.replace('detail = "An unexpected server error occurred" if _is_production() else', 'detail = "An unexpected server error occurred" if _is_production(app_settings) else')

# 11. Update evidence export endpoint with per-case and per-requirement reports
# This is a complex replacement - let me find the exact function and replace it
old_evidence_export = '''    @api.get("/api/export/evidence/{run_id}", dependencies=[Depends(authenticate)])
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
        return Response(content=archive_buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{run_id}-evidence.zip'"})'''

new_evidence_export = '''    @api.get("/api/export/evidence/{run_id}", dependencies=[Depends(authenticate)])
    async def export_evidence(run_id: str) -> Response:
        run_item = next((item for item in services.repository.history() if item["id"] == run_id), None)
        if not run_item:
            raise HTTPException(status_code=404, detail="Run was not found")
        results = services.repository.results(run_id)
        
        # Build detailed results with stepwise information
        result_details = []
        for result in results:
            steps = services.repository.step_results(result["id"])
            case = next((c for c in services.repository.test_cases() if c["id"] == result["test_case_id"]), None)
            requirement = next((r for r in services.repository.requirements() if r["id"] == result.get("requirement_id")), None) if result.get("requirement_id") else None
            
            detailed_result = {
                **result,
                "steps": steps,
                "test_case": case,
                "requirement": requirement,
            }
            result_details.append(detailed_result)
        
        # Create per-test-case reports
        per_case_reports = {}
        for result in result_details:
            case_id = result["test_case_id"]
            case = result.get("test_case")
            requirement = result.get("requirement")
            
            # Build stepwise report with screenshot references
            step_reports = []
            for step in result.get("steps", []):
                step_report = {
                    "step_number": step.get("step_number"),
                    "action": step.get("action"),
                    "expected": step.get("expected"),
                    "actual": step.get("actual"),
                    "status": step.get("status"),
                    "duration": step.get("duration"),
                    "locator": step.get("locator"),
                    "error": step.get("error"),
                    "page_url": step.get("page_url"),
                    "page_title": step.get("page_title"),
                    "before_screenshot": step.get("before_screenshot_path"),
                    "after_screenshot": step.get("screenshot_path"),
                }
                step_reports.append(step_report)
            
            per_case_reports[case_id] = {
                "run_id": run_id,
                "test_case_id": case_id,
                "test_case_title": case.get("title") if case else "",
                "test_case_type": case.get("test_type") if case else "",
                "test_case_priority": case.get("priority") if case else "",
                "requirement_id": requirement.get("id") if requirement else result.get("requirement_id"),
                "requirement_title": requirement.get("title") if requirement else "",
                "requirement_user_story": requirement.get("user_story") if requirement else "",
                "overall_status": result.get("status"),
                "overall_duration": result.get("duration"),
                "overall_error": result.get("error"),
                "steps": step_reports,
            }
        
        # Create full consolidated report
        full_report = {
            "run": run_item,
            "summary": {
                "total_cases": len(result_details),
                "passed": sum(1 for r in result_details if r.get("status") == "PASS"),
                "failed": sum(1 for r in result_details if r.get("status") == "FAIL"),
                "blocked": sum(1 for r in result_details if r.get("status") == "BLOCKED"),
                "simulated": sum(1 for r in result_details if r.get("status") == "SIMULATED"),
                "total_duration": sum(r.get("duration", 0) for r in result_details),
            },
            "test_cases": result_details,
        }
        
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            # Full consolidated report
            archive.writestr("full-report.json", json.dumps(full_report, indent=2))
            
            # Per-test-case reports (one JSON per test case)
            for case_id, case_report in per_case_reports.items():
                archive.writestr(f"reports/{case_id}.json", json.dumps(case_report, indent=2))
            
            # Per-requirement (user story) consolidated reports
            req_groups = {}
            for case_id, case_report in per_case_reports.items():
                req_id = case_report.get("requirement_id", "unknown")
                if req_id not in req_groups:
                    req_groups[req_id] = {
                        "requirement_id": req_id,
                        "requirement_title": case_report.get("requirement_title"),
                        "requirement_user_story": case_report.get("requirement_user_story"),
                        "test_cases": [],
                    }
                req_groups[req_id]["test_cases"].append(case_report)
            
            for req_id, req_report in req_groups.items():
                archive.writestr(f"reports/requirement-{req_id}.json", json.dumps(req_report, indent=2))
            
            # Existing files
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
        
        return Response(content=archive_buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{run_id}-evidence.zip'"})'''

content = content.replace(old_evidence_export, new_evidence_export)

# Write the modified content
open('src/ui_automation/api.py', 'w').write(content)
print("Applied all fixes to api.py")