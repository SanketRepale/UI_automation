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


def evidence_archive(results: list[dict[str, Any]], scripts: dict[str, str], locators: list[dict[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
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
                        from pathlib import Path
                        evidence = Path(path)
                        archive.write(evidence, f"screenshots/{result['test_case_id']}/{evidence.name}")
                    except OSError:
                        continue
    return buffer.getvalue()
