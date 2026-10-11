from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pandas as pd


def test_cases_frame(cases: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([{key: json.dumps(value, ensure_ascii=True) if isinstance(value, (dict, list)) else value for key, value in case.items()} for case in cases])


def make_export(cases: list[dict[str, Any]], format_name: str) -> tuple[bytes, str, str]:
    frame = test_cases_frame(cases)
    if format_name == "CSV":
        return frame.to_csv(index=False).encode("utf-8"), "text/csv", "test-cases.csv"
    if format_name == "Excel":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            frame.to_excel(writer, index=False, sheet_name="Test Cases")
        return buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "test-cases.xlsx"
    if format_name == "JSON":
        return json.dumps(cases, indent=2).encode("utf-8"), "application/json", "test-cases.json"
    markdown = []
    for case in cases:
        markdown.extend([f"## {case.get('id', '')}: {case.get('title', '')}", "", f"- Requirement: {case.get('requirement_id', '')}", f"- Type: {case.get('test_type', '')}", f"- Priority: {case.get('priority', '')}", f"- Status: {case.get('status', '')}", "", "| Step | Action | Expected result |", "| --- | --- | --- |"])
        markdown.extend(f"| {step.get('number', '')} | {step.get('action', '')} | {step.get('expected_result', '')} |" for step in case.get("steps", []))
        markdown.append("")
    return "\n".join(markdown).encode("utf-8"), "text/markdown", "test-cases.md"


def evidence_archive(results: list[dict[str, Any]], scripts: dict[str, str], locators: list[dict[str, Any]], repository=None, settings=None) -> bytes:
    import io
    import json
    import zipfile
    from pathlib import Path
    
    # Build detailed results with stepwise information
    result_details = []
    for result in results:
        steps = result.get("steps", [])
        detailed_result = {**result, "steps": steps}
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
        
        # Per-test-case reports
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
        archive.writestr("test_results.json", json.dumps(results, indent=2))
        archive.writestr("locators.json", json.dumps(locators, indent=2))
        
        for test_case_id, source in scripts.items():
            archive.writestr(f"scripts/{test_case_id}.py", source)
        
        for result in results:
            for step in result.get("steps", []):
                for path in (step.get("before_screenshot_path"), step.get("screenshot_path")):
                    if not path:
                        continue
                    try:
                        evidence = Path(path)
                        archive.write(evidence, f"screenshots/{result['test_case_id']}/{evidence.name}")
                    except OSError:
                        continue
    
    return archive_buffer.getvalue()
