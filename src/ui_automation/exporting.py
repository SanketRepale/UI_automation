from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from typing import Any

import pandas as pd
from fpdf import FPDF


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


class TestReportPDF(FPDF):
    """Custom PDF class for test reports."""

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 5, f"Fieldnotes QA Test Report - Page {self.page_no()}", align="C")
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title: str):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(0, 102, 204)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def sub_section_title(self, title: str):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(60, 60, 60)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def body_text(self, text: str):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5, text)
        self.ln(2)

    def key_value(self, key: str, value: str):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(60, 60, 60)
        key_w = self.get_string_width(key + ": ") + 2
        self.cell(key_w, 5, key + ": ")
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5, value)
        self.ln(1)

    def status_badge(self, status: str):
        colors = {
            "PASS": (34, 139, 34),
            "FAIL": (220, 20, 60),
            "BLOCKED": (255, 140, 0),
            "SIMULATED": (100, 100, 100),
            "SKIPPED": (128, 128, 128),
        }
        r, g, b = colors.get(status, (100, 100, 100))
        self.set_fill_color(r, g, b)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 9)
        self.cell(self.get_string_width(status) + 6, 6, status, fill=True, align="C")
        self.ln(8)

    def step_table_header(self):
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(0, 102, 204)
        self.set_text_color(255, 255, 255)
        col_widths = [12, 55, 45, 45, 15, 15]
        headers = ["Step", "Action", "Expected", "Actual", "Status", "Dur(s)"]
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
        self.ln()

    def step_row(self, step: dict, col_widths: list):
        self.set_font("Helvetica", "", 7)
        self.set_text_color(40, 40, 40)
        status = step.get("status", "")
        colors = {
            "PASS": (34, 139, 34),
            "FAIL": (220, 20, 60),
            "BLOCKED": (255, 140, 0),
            "SIMULATED": (100, 100, 100),
            "SKIPPED": (128, 128, 128),
        }
        r, g, b = colors.get(status, (100, 100, 100))
        self.set_fill_color(r, g, b)
        self.set_text_color(255, 255, 255)
        
        step_num = str(step.get("step_number", ""))
        action = step.get("action", "")[:50]
        expected = step.get("expected", "")[:40]
        actual = step.get("actual", "")[:40]
        duration = f"{step.get('duration', 0):.2f}"
        
        self.cell(col_widths[0], 6, step_num, border=1, align="C")
        self.cell(col_widths[1], 6, action, border=1)
        self.cell(col_widths[2], 6, expected, border=1)
        self.cell(col_widths[3], 6, actual, border=1)
        self.cell(col_widths[4], 6, status, border=1, fill=True, align="C")
        self.cell(col_widths[5], 6, duration, border=1, align="C")
        self.ln()


def generate_pdf_report(full_report: dict, per_case_reports: dict, req_groups: dict) -> bytes:
    """Generate a comprehensive PDF report."""
    pdf = TestReportPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    
    # Cover page
    pdf.add_page()
    pdf.ln(30)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(0, 102, 204)
    pdf.cell(0, 15, "Fieldnotes QA", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 18)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 12, "Test Execution Report", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(100, 100, 100)
    run_info = full_report.get("run", {})
    pdf.cell(0, 8, f"Run ID: {run_info.get('id', 'N/A')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Environment: {run_info.get('environment', 'N/A')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)
    pdf.set_draw_color(0, 102, 204)
    pdf.line(60, pdf.get_y(), pdf.w - 60, pdf.get_y())
    pdf.ln(10)
    
    # Summary
    summary = full_report.get("summary", {})
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, "Execution Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(40, 40, 40)
    summary_items = [
        ("Total Test Cases", str(summary.get("total_cases", 0))),
        ("Passed", str(summary.get("passed", 0))),
        ("Failed", str(summary.get("failed", 0))),
        ("Blocked", str(summary.get("blocked", 0))),
        ("Simulated", str(summary.get("simulated", 0))),
        ("Total Duration", f"{summary.get('total_duration', 0):.2f}s"),
    ]
    for key, value in summary_items:
        pdf.key_value(key, value)
    
    # Per-requirement (User Story) reports
    for req_id, req_report in req_groups.items():
        pdf.add_page()
        pdf.section_title(f"User Story: {req_report.get('requirement_title', req_id)}")
        if req_report.get("requirement_user_story"):
            pdf.sub_section_title("User Story")
            pdf.body_text(req_report["requirement_user_story"])
        
        pdf.sub_section_title(f"Test Cases ({len(req_report['test_cases'])})")
        
        for case_report in req_report["test_cases"]:
            pdf.sub_section_title(f"{case_report['test_case_id']}: {case_report.get('test_case_title', '')}")
            pdf.key_value("Type", case_report.get("test_case_type", ""))
            pdf.key_value("Priority", case_report.get("test_case_priority", ""))
            pdf.key_value("Overall Status", case_report.get("overall_status", ""))
            pdf.key_value("Duration", f"{case_report.get('overall_duration', 0):.2f}s")
            if case_report.get("overall_error"):
                pdf.key_value("Error", case_report["overall_error"])
            
            # Step table
            pdf.ln(2)
            col_widths = [12, 55, 45, 45, 15, 15]
            pdf.step_table_header()
            for step in case_report.get("steps", []):
                if pdf.get_y() > pdf.h - 30:
                    pdf.add_page()
                    pdf.step_table_header()
                pdf.step_row(step, col_widths)
            pdf.ln(4)
    
    # Full consolidated test cases
    pdf.add_page()
    pdf.section_title("All Test Cases (Consolidated)")
    for result in full_report.get("test_cases", []):
        pdf.sub_section_title(f"{result.get('test_case_id', 'N/A')}: {result.get('title', '')}")
        pdf.key_value("Requirement", result.get("requirement_id", "N/A"))
        pdf.key_value("Status", result.get("status", "N/A"))
        pdf.key_value("Duration", f"{result.get('duration', 0):.2f}s")
        if result.get("error"):
            pdf.key_value("Error", result["error"])
        
        steps = result.get("steps", [])
        if steps:
            pdf.ln(2)
            col_widths = [12, 55, 45, 45, 15, 15]
            pdf.step_table_header()
            for step in steps:
                if pdf.get_y() > pdf.h - 30:
                    pdf.add_page()
                    pdf.step_table_header()
                pdf.step_row(step, col_widths)
            pdf.ln(4)
    
    return bytes(pdf.output(dest="S"))


def generate_html_report(full_report: dict, per_case_reports: dict, req_groups: dict) -> str:
    """Generate a comprehensive HTML report."""
    summary = full_report.get("summary", {})
    run_info = full_report.get("run", {})
    generated_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    
    status_colors = {
        "PASS": "#22c55e",
        "FAIL": "#ef4444",
        "BLOCKED": "#f97316",
        "SIMULATED": "#6b7280",
        "SKIPPED": "#9ca3af",
    }
    
    def status_badge(status: str) -> str:
        color = status_colors.get(status, "#6b7280")
        return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{status}</span>'
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fieldnotes QA - Test Execution Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1f2937; max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .header {{ text-align: center; padding: 40px 0; border-bottom: 2px solid #0066cc; margin-bottom: 30px; }}
        .header h1 {{ color: #0066cc; margin: 0; font-size: 2.5rem; }}
        .header .subtitle {{ color: #6b7280; font-size: 1.2rem; margin-top: 8px; }}
        .header .meta {{ color: #9ca3af; font-size: 0.9rem; margin-top: 16px; }}
        .section {{ margin-bottom: 40px; }}
        .section h2 {{ color: #1f2937; border-bottom: 2px solid #0066cc; padding-bottom: 8px; }}
        .section h3 {{ color: #374151; margin-top: 24px; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin: 20px 0; }}
        .summary-card {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; text-align: center; }}
        .summary-card .label {{ font-size: 0.875rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; }}
        .summary-card .value {{ font-size: 2rem; font-weight: bold; color: #1f2937; margin-top: 4px; }}
        .test-case {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
        .test-case-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
        .test-case-title {{ font-size: 1.1rem; font-weight: 600; color: #1f2937; }}
        .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 16px 0; }}
        .meta-item {{ background: #f9fafb; padding: 12px; border-radius: 6px; }}
        .meta-label {{ font-size: 0.75rem; color: #6b7280; text-transform: uppercase; }}
        .meta-value {{ font-weight: 500; color: #1f2937; margin-top: 2px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 0.875rem; }}
        th, td {{ padding: 8px 12px; text-align: left; border: 1px solid #e5e7eb; }}
        th {{ background: #0066cc; color: white; font-weight: 600; }}
        tr:nth-child(even) {{ background: #f9fafb; }}
        .status-cell {{ font-weight: 600; text-align: center; }}
        .error {{ background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; padding: 12px; border-radius: 6px; margin: 12px 0; }}
        .user-story {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 20px; margin: 20px 0; }}
        .user-story h3 {{ margin-top: 0; color: #1e40af; }}
        .toc {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin-bottom: 30px; }}
        .toc ul {{ list-style: none; padding: 0; }}
        .toc li {{ padding: 8px 0; border-bottom: 1px solid #e5e7eb; }}
        .toc a {{ color: #0066cc; text-decoration: none; }}
        .toc a:hover {{ text-decoration: underline; }}
        .screenshot {{ max-width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 4px; margin: 4px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Fieldnotes QA</h1>
        <div class="subtitle">Test Execution Report</div>
        <div class="meta">
            Run ID: {run_info.get('id', 'N/A')} | 
            Generated: {generated_at} | 
            Environment: {run_info.get('environment', 'N/A')}
        </div>
    </div>

    <nav class="toc" aria-label="Table of Contents">
        <h3>Table of Contents</h3>
        <ul>
            <li><a href="#summary">Execution Summary</a></li>
"""
    
    # Add TOC entries for each requirement
    for req_id, req_report in req_groups.items():
        title = req_report.get('requirement_title', req_id)
        html += f'            <li><a href="#req-{req_id}">{title} ({len(req_report["test_cases"])} test cases)</a></li>\n'
    
    html += """        </ul>
    </nav>

    <section id="summary">
        <h2>Execution Summary</h2>
        <div class="summary-grid">
"""
    
    summary_items = [
        ("Total Test Cases", str(summary.get("total_cases", 0)), "#1f2937"),
        ("Passed", str(summary.get("passed", 0)), "#22c55e"),
        ("Failed", str(summary.get("failed", 0)), "#ef4444"),
        ("Blocked", str(summary.get("blocked", 0)), "#f97316"),
        ("Simulated", str(summary.get("simulated", 0)), "#6b7280"),
        ("Total Duration", f"{summary.get('total_duration', 0):.2f}s", "#1f2937"),
    ]
    
    for label, value, color in summary_items:
        html += f"""            <div class="summary-card">
                <div class="label">{label}</div>
                <div class="value" style="color:{color};">{value}</div>
            </div>
"""
    
    html += """        </div>
    </section>
"""
    
    # Per-requirement reports
    for req_id, req_report in req_groups.items():
        title = req_report.get('requirement_title', req_id)
        user_story = req_report.get('requirement_user_story', '')
        
        html += f"""    <section id="req-{req_id}">
        <h2>User Story: {title}</h2>
"""
        if user_story:
            html += f"""        <div class="user-story">
            <h3>User Story</h3>
            <p>{user_story}</p>
        </div>
"""
        
        html += f"""        <h3>Test Cases ({len(req_report['test_cases'])})</h3>
"""
        
        for case_report in req_report["test_cases"]:
            case_id = case_report['test_case_id']
            case_title = case_report.get('test_case_title', '')
            case_type = case_report.get('test_case_type', '')
            priority = case_report.get('test_case_priority', '')
            overall_status = case_report.get('overall_status', '')
            overall_duration = case_report.get('overall_duration', 0)
            overall_error = case_report.get('overall_error', '')
            
            html += f"""        <div class="test-case">
            <div class="test-case-header">
                <span class="test-case-title">{case_id}: {case_title}</span>
                {status_badge(overall_status)}
            </div>
            <div class="meta-grid">
                <div class="meta-item"><div class="meta-label">Type</div><div class="meta-value">{case_type}</div></div>
                <div class="meta-item"><div class="meta-label">Priority</div><div class="meta-value">{priority}</div></div>
                <div class="meta-item"><div class="meta-label">Duration</div><div class="meta-value">{overall_duration:.2f}s</div></div>
            </div>
"""
            if overall_error:
                html += f'            <div class="error">{overall_error}</div>\n'
            
            steps = case_report.get("steps", [])
            if steps:
                html += """            <table>
                <thead>
                    <tr>
                        <th>Step</th>
                        <th>Action</th>
                        <th>Expected</th>
                        <th>Actual</th>
                        <th>Status</th>
                        <th>Duration (s)</th>
                    </tr>
                </thead>
                <tbody>
"""
                for step in steps:
                    step_status = step.get('status', '')
                    html += f"""                    <tr>
                        <td>{step.get('step_number', '')}</td>
                        <td>{step.get('action', '')}</td>
                        <td>{step.get('expected', '')}</td>
                        <td>{step.get('actual', '')}</td>
                        <td class="status-cell">{status_badge(step_status)}</td>
                        <td>{step.get('duration', 0):.2f}</td>
                    </tr>
"""
                html += """                </tbody>
            </table>
"""
            html += """        </div>
"""
    
    html += """    </section>

    <section id="all-cases">
        <h2>All Test Cases (Consolidated)</h2>
"""
    
    for result in full_report.get("test_cases", []):
        case_id = result.get('test_case_id', 'N/A')
        title = result.get('title', '')
        req_id = result.get('requirement_id', 'N/A')
        status = result.get('status', 'N/A')
        duration = result.get('duration', 0)
        error = result.get('error', '')
        
        html += f"""        <div class="test-case">
            <div class="test-case-header">
                <span class="test-case-title">{case_id}: {title}</span>
                {status_badge(status)}
            </div>
            <div class="meta-grid">
                <div class="meta-item"><div class="meta-label">Requirement</div><div class="meta-value">{req_id}</div></div>
                <div class="meta-item"><div class="meta-label">Duration</div><div class="meta-value">{duration:.2f}s</div></div>
            </div>
"""
        if error:
            html += f'            <div class="error">{error}</div>\n'
        
        steps = result.get("steps", [])
        if steps:
            html += """            <table>
                <thead>
                    <tr>
                        <th>Step</th>
                        <th>Action</th>
                        <th>Expected</th>
                        <th>Actual</th>
                        <th>Status</th>
                        <th>Duration (s)</th>
                    </tr>
                </thead>
                <tbody>
"""
            for step in steps:
                step_status = step.get('status', '')
                html += f"""                    <tr>
                        <td>{step.get('step_number', '')}</td>
                        <td>{step.get('action', '')}</td>
                        <td>{step.get('expected', '')}</td>
                        <td>{step.get('actual', '')}</td>
                        <td class="status-cell">{status_badge(step_status)}</td>
                        <td>{step.get('duration', 0):.2f}</td>
                    </tr>
"""
            html += """                </tbody>
            </table>
"""
        html += """        </div>
"""
    
    html += """    </section>
</body>
</html>"""
    
    return html


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
    
    # Generate PDF and HTML reports
    pdf_bytes = generate_pdf_report(full_report, per_case_reports, req_groups)
    html_content = generate_html_report(full_report, per_case_reports, req_groups)
    
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        # Full consolidated report (JSON)
        archive.writestr("full-report.json", json.dumps(full_report, indent=2))
        
        # PDF report
        archive.writestr("report.pdf", pdf_bytes)
        
        # HTML report
        archive.writestr("report.html", html_content.encode("utf-8"))
        
        # Per-test-case reports (JSON)
        for case_id, case_report in per_case_reports.items():
            archive.writestr(f"reports/{case_id}.json", json.dumps(case_report, indent=2))
        
        # Per-requirement (user story) consolidated reports (JSON)
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