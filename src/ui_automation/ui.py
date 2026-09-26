from __future__ import annotations

import ast
import json
import logging
import re
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ui_automation.agents import PlaywrightScriptAgent, RequirementAgent, TestCaseAgent, TestCaseReviewAgent
from ui_automation.config import Settings
from ui_automation.documents import extract_text
from ui_automation.documents import extract_application_details
from ui_automation.exporting import evidence_archive, make_export
from ui_automation.executor import ExecutionService
from ui_automation.llm import LLMProvider
from ui_automation.locator_service import LocatorService
from ui_automation.repository import Repository
from ui_automation.utils import log_event

NAV_ITEMS = ["Dashboard", "Requirements", "Test Case Generation", "Test Cases", "Find Elements", "Script Generation", "Test Execution", "Execution History", "Reporting", "Settings"]


def render(repository: Repository, settings: Settings, logger: logging.Logger) -> None:
    st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
    :root { --ink:#172526; --muted:#667574; --line:#dce5e1; --accent:#007e72; --lime:#d7ee8c; --paper:#f6f8f4; }
    .stApp { background:var(--paper); color:var(--ink); font-family:'DM Sans',sans-serif; }
    h1,h2,h3 { font-family:'Space Grotesk',sans-serif !important; letter-spacing:0 !important; color:var(--ink); }
    [data-testid="stSidebar"] { background:#e9f0e9; border-right:1px solid var(--line); }
    [data-testid="stSidebar"] h1 { font-size:1.28rem; }
    div[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:6px; padding:16px 18px; }
    div[data-testid="stMetricValue"] { color:var(--ink); font-family:'Space Grotesk',sans-serif; }
    .eyebrow { color:var(--accent); text-transform:uppercase; font-size:.74rem; font-weight:700; letter-spacing:.08em; }
    .workflow { border-left:3px solid var(--accent); padding:8px 12px; background:#edf5ed; border-radius:0 4px 4px 0; }
    button[kind="primary"] { background:#007e72; border-color:#007e72; }
    code, pre { font-family:Consolas,monospace !important; }
    </style>""", unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### ◉ Fieldnotes QA")
        st.caption("AI-assisted UI test workbench")
        page = st.radio("Workspace", NAV_ITEMS, label_visibility="collapsed")
        st.divider()
        cases = repository.test_cases()
        requirements = repository.requirements()
        st.markdown("<div class='workflow'><b>Workflow</b><br>Requirements → Cases → Locators → Scripts → Runs → Reports</div>", unsafe_allow_html=True)
        st.caption(f"{len(requirements)} requirements · {len(cases)} test cases")

    llm = _provider(settings)
    if page == "Dashboard":
        _dashboard(repository, settings, llm)
    elif page == "Requirements":
        _requirements(repository, settings, llm, logger)
    elif page == "Test Case Generation":
        _generation(repository, settings, llm, logger)
    elif page == "Test Cases":
        _test_cases(repository, settings)
    elif page == "Find Elements":
        _locators(repository, settings, logger)
    elif page == "Script Generation":
        _scripts(repository, settings, llm, logger)
    elif page == "Test Execution":
        _execution(repository, settings, logger)
    elif page == "Execution History":
        _history(repository)
    elif page == "Reporting":
        _reporting(repository)
    else:
        _settings(settings, llm)


def _provider(settings: Settings) -> LLMProvider:
    return LLMProvider(
        provider=st.session_state.get("llm_provider", settings.llm_provider),
        base_url=st.session_state.get("llm_base_url", settings.llm_base_url),
        model=st.session_state.get("llm_model", settings.llm_model),
        api_key=st.session_state.get("llm_api_key", settings.llm_api_key),
    )


def _title(kicker: str, title: str, subtitle: str = "") -> None:
    st.markdown(f"<div class='eyebrow'>{kicker}</div>", unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def _render_case_details(case: dict[str, Any]) -> None:
    if case.get("preconditions"):
        st.markdown("**Preconditions**")
        for condition in case["preconditions"]:
            st.markdown(f"- {condition}")
    if case.get("test_data"):
        st.markdown("**Test data**")
        st.write(case["test_data"] if isinstance(case["test_data"], str) else "; ".join(f"{key}: {value}" for key, value in case["test_data"].items()))
    expected_results = case.get("expected_results", [])
    if expected_results:
        st.markdown("**Expected results**")
        for result in expected_results:
            st.markdown(f"- {result}")
    steps = case.get("steps", [])
    if steps:
        st.markdown("**Test steps**")
        rows = [{
            "Step": step.get("number", index),
            "Action": step.get("action", ""),
            "Test data": step.get("test_data", ""),
            "Expected result": step.get("expected_result", ""),
            "Locator requirement": step.get("locator_requirement", ""),
        } for index, step in enumerate(steps, 1)]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    if case.get("generation_note"):
        st.caption(case["generation_note"])


def _dashboard(repository: Repository, settings: Settings, llm: LLMProvider) -> None:
    _title("Overview", "Automation workspace", "Move from source requirements to reviewed browser evidence.")
    cases = repository.test_cases()
    results = repository.results()
    runs = repository.history()
    counts = Counter(row["status"] for row in results)
    total = len(results)
    passed = counts["PASS"]
    first, second, third, fourth = st.columns(4)
    first.metric("Requirements", len(repository.requirements()))
    second.metric("Test cases", len(cases))
    third.metric("Latest run", runs[0]["id"][:12] if runs else "None yet")
    fourth.metric("Pass rate", f"{passed / total:.0%}" if total else "—", f"{passed} passed · {counts['FAIL']} failed")
    st.subheader("Next steps")
    stages = [("01", "Upload requirements", "Analyze uploaded source documents."), ("02", "Find story elements", "Enter the page URL and optional sign-in guidance once per story."), ("03", "Review and automate", "Approve cases, inspect shared locators, and review scripts."), ("04", "Execute and report", "Run approved cases with their story’s shared elements.")]
    columns = st.columns(4)
    for column, (number, name, detail) in zip(columns, stages):
        column.markdown(f"**{number} / {name}**")
        column.caption(detail)
    if results:
        st.subheader("Recent execution outcomes")
        st.dataframe(pd.DataFrame(results[:12])[ ["test_case_id", "title", "status", "duration", "run_id"] ], width="stretch", hide_index=True)
    else:
        st.info("No test executions are recorded. Generated scripts and drafts are not counted as test results.")
    st.caption(f"LLM: {'configured' if llm.configured else 'offline draft mode'} · Browser: {settings.browser or 'not configured'} · Data: SQLite")


def _requirements(repository: Repository, settings: Settings, llm: LLMProvider, logger: logging.Logger) -> None:
    _title("01 / Source", "Requirements", "Upload source documents. Stories and acceptance criteria are extracted from the files.")
    uploads = st.file_uploader("Requirement documents", type=["pdf", "docx", "xlsx", "csv", "txt", "md", "markdown"], accept_multiple_files=True, key="requirement-upload")
    if st.button("Analyze uploaded documents", type="primary", disabled=not uploads):
        file_names: list[str] = []
        extracted_documents: list[tuple[str, str]] = []
        with st.spinner("Extracting uploaded files and analyzing requirements…"):
            for uploaded in uploads or []:
                safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(uploaded.name).name)
                content = uploaded.getvalue()
                destination = settings.uploads_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}-{safe_name}"
                destination.write_bytes(content)
                file_names.append(destination.name)
                try:
                    extracted_documents.append((uploaded.name, extract_text(uploaded.name, content)))
                except Exception as error:
                    st.warning(f"Could not extract {uploaded.name}: {error}")
            if not extracted_documents:
                st.error("No uploaded file could be read. Check that the document is not encrypted or damaged.")
            else:
                try:
                    analysis, application, mode = RequirementAgent(settings.skills_dir, llm).analyze_documents(extracted_documents)
                    requirement_id = f"REQ-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                    title = analysis.get("requirement_title") or Path(uploads[0].name).stem
                    safe_analysis = {key: value for key, value in analysis.items() if key not in {"username", "password", "credentials"}}
                    st.session_state["active_requirement"] = requirement_id
                    if application.get("username") or application.get("password"):
                        st.session_state.setdefault("requirement_credentials", {})[requirement_id] = {
                            "username": application.get("username", ""),
                            "password": application.get("password", ""),
                        }
                    safe_analysis["application_details"] = {key: value for key, value in application.items() if key not in {"username", "password"}}
                    repository.save_requirement(requirement_id, title, analysis.get("user_story", ""), analysis.get("acceptance_criteria", []), safe_analysis, file_names)
                    settings_url = extract_application_details(settings.target_url).get("application_url") if settings.target_url else None
                    application_url = application.get("application_url") or settings_url or ""
                    if application_url:
                        repository.save_requirement_target({
                            "requirement_id": requirement_id,
                            "application_url": application_url,
                            "authentication_type": application.get("authentication_type") or settings.authentication_type or "No Authentication",
                            "browser": application.get("browser") or (settings.browser if settings.browser_configured else "chromium"),
                            "headless": application.get("execution_mode", "headless" if settings.headless else "headed") == "headless",
                            "username_label": application.get("username_label") or settings.username_label or "",
                            "password_label": application.get("password_label") or settings.password_label or "",
                            "submit_label": application.get("submit_label") or settings.submit_label or "",
                            "guidance": "",
                        })
                    log_event(logger, "RequirementAgent", "requirement_analyzed", requirement_id=requirement_id, analysis_mode=mode, target_url_available=bool(application.get("application_url") or settings.target_url), uploaded_file_count=len(file_names))
                    st.success(f"Saved {requirement_id} · {mode}")
                    if not application_url:
                        st.info("Add the website URL and optional sign-in details on Find Elements when you are ready to inspect the story.")
                    st.markdown("**User story**")
                    st.write(safe_analysis.get("user_story") or "No user story supplied.")
                    st.markdown("**Acceptance criteria**")
                    for criterion in safe_analysis.get("acceptance_criteria", []):
                        st.markdown(f"- {criterion}")
                except Exception as error:
                    st.error(f"Requirement analysis failed: {error}")
    requirements = repository.requirements()
    if requirements:
        st.subheader("Saved requirements")
        selected = st.selectbox("Inspect requirement", requirements, format_func=lambda item: f"{item['id']} · {item['title']}")
        st.markdown(f"**Story**\n\n{selected['user_story'] or 'No user story supplied.'}")
        with st.expander("Acceptance criteria and source files", expanded=True):
            for criterion in selected["acceptance_criteria"]:
                st.markdown(f"- {criterion}")
            st.caption("Files: " + (", ".join(selected["source_files"]) or "None"))
        confirm_delete = st.checkbox("Confirm requirement deletion", key=f"confirm-delete-requirement-{selected['id']}")
        if st.button("Delete requirement and its test cases", disabled=not confirm_delete, key=f"delete-requirement-{selected['id']}"):
            dependent_case_count = sum(case.get("requirement_id") == selected["id"] for case in repository.test_cases())
            repository.delete_requirement(selected["id"])
            st.session_state.get("requirement_credentials", {}).pop(selected["id"], None)
            log_event(logger, "RequirementAgent", "requirement_deleted", requirement_id=selected["id"], deleted_case_count=dependent_case_count)
            st.success(f"Deleted requirement {selected['id']} and {dependent_case_count} test cases.")
            st.rerun()


def _generation(repository: Repository, settings: Settings, llm: LLMProvider, logger: logging.Logger) -> None:
    _title("02 / Draft", "Test case generation", "Generate cases from analyzed criteria; every case remains a draft until reviewed.")
    requirements = repository.requirements()
    if not requirements:
        st.info("Save a requirement before generating test cases.")
        return
    requirement = st.selectbox("Requirement", requirements, format_func=lambda item: f"{item['id']} · {item['title']}")
    st.markdown("**User story**")
    st.write(requirement["user_story"] or "No user story supplied.")
    st.markdown("**Acceptance criteria**")
    for criterion in requirement["acceptance_criteria"]:
        st.markdown(f"- {criterion}")
    if st.button("Generate test case drafts", type="primary"):
        try:
            log_event(logger, "TestCaseAgent", "test_case_generation_started", requirement_id=requirement["id"])
            with st.spinner("Generating reviewable positive and negative cases…"):
                generated, mode = TestCaseAgent(settings.skills_dir, llm).generate(requirement["id"], requirement["analysis"])
            existing_cases = repository.test_cases()
            stale_drafts = [case for case in existing_cases if case.get("requirement_id") == requirement["id"] and case.get("status") == "Draft"]
            if generated:
                for stale_case in stale_drafts:
                    repository.delete_test_case(stale_case["id"])
            stale_ids = {case["id"] for case in stale_drafts}
            existing = {case["id"] for case in existing_cases if case["id"] not in stale_ids}
            next_number = len(existing) + 1
            for case in generated:
                while f"TC-{next_number:03d}" in existing:
                    next_number += 1
                case["id"] = f"TC-{next_number:03d}"
                case["status"] = "Draft"
                case["requirement_id"] = requirement["id"]
                repository.save_test_case(case)
                existing.add(case["id"])
                next_number += 1
            log_event(logger, "TestCaseAgent", "test_case_generation_completed", requirement_id=requirement["id"], generated_case_count=len(generated), generation_mode=mode)
            st.success(f"Created {len(generated)} reviewable drafts · {mode}")
            if mode.startswith("Offline"):
                st.warning("Offline drafts use source text and heuristics only. They are not LLM-generated or application-verified.")
            if generated:
                st.dataframe(pd.DataFrame([{ "ID": case["id"], "Title": case["title"], "Type": case["test_type"], "Priority": case["priority"], "Status": case["status"] } for case in generated]), width="stretch", hide_index=True)
                for case in generated:
                    with st.expander(f"{case['id']} · {case['title']}"):
                        _render_case_details(case)
        except Exception as error:
            log_event(logger, "TestCaseAgent", "test_case_generation_failed", level=logging.ERROR, requirement_id=requirement["id"], error=f"{type(error).__name__}: {error}")
            st.error(f"Generation failed: {error}")


def _test_cases(repository: Repository, settings: Settings) -> None:
    _title("03 / Human review", "Test cases", "Search, filter, edit the structured case, and explicitly approve or reject it.")
    cases = repository.test_cases()
    if not cases:
        st.info("No test cases yet. Generate drafts from a requirement first.")
        return
    requirements = repository.requirements()
    requirement_ids = ["All"] + sorted({case.get("requirement_id", "") for case in cases})
    col1, col2, col3 = st.columns(3)
    query = col1.text_input("Search", placeholder="ID or title")
    priorities = ["All"] + sorted({case.get("priority", "Medium") for case in cases})
    priority = col2.selectbox("Priority", priorities)
    test_types = ["All"] + sorted({case.get("test_type", "Functional") for case in cases})
    test_type = col3.selectbox("Test type", test_types)
    requirement_id = st.selectbox("Requirement filter", requirement_ids)
    filtered = [case for case in cases if (not query or query.lower() in (case["id"] + case["title"]).lower()) and (priority == "All" or case.get("priority") == priority) and (test_type == "All" or case.get("test_type") == test_type) and (requirement_id == "All" or case.get("requirement_id") == requirement_id)]
    st.dataframe(pd.DataFrame([{ "ID": case["id"], "Title": case["title"], "Requirement": case["requirement_id"], "Type": case.get("test_type"), "Priority": case.get("priority"), "Review status": case.get("status") } for case in filtered]), width="stretch", hide_index=True)
    if not filtered:
        st.warning("No cases match these filters.")
        return
    for case in filtered:
        with st.expander(f"{case['id']} · {case['title']} · {case.get('status', 'Draft')}"):
            _render_case_details(case)
    selected = st.selectbox("Open test case", filtered, format_func=lambda item: f"{item['id']} · {item['title']}")
    criteria = next((item["acceptance_criteria"] for item in requirements if item["id"] == selected.get("requirement_id")), [])
    issues = TestCaseReviewAgent(settings.skills_dir, _provider(settings)).review(selected, criteria)
    if issues:
        st.warning("Review findings: " + " · ".join(issues))
    else:
        st.success("Basic structure and criterion traceability checks passed. Human approval is still required.")
    with st.form(f"edit-case-{selected['id']}"):
        edited_title = st.text_input("Title", value=selected.get("title", ""))
        edited_type = st.text_input("Test type", value=selected.get("test_type", "Functional"))
        edited_priority = st.text_input("Priority", value=selected.get("priority", "Medium"))
        edited_steps = []
        for index, step in enumerate(selected.get("steps", []), 1):
            st.markdown(f"**Step {index}**")
            edited_steps.append({
                **step,
                "action": st.text_input("Action", value=step.get("action", ""), key=f"edit-action-{selected['id']}-{index}"),
                "expected_result": st.text_area("Expected result", value=step.get("expected_result", ""), height=70, key=f"edit-expected-{selected['id']}-{index}"),
            })
        save_edits = st.form_submit_button("Save edits")
    if save_edits:
        replacement = {**selected, "title": edited_title, "test_type": edited_type, "priority": edited_priority, "steps": edited_steps}
        repository.save_test_case(replacement)
        st.success("Saved test case.")
        st.rerun()
    left, right, third, fourth = st.columns(4)
    if right.button("Approve", type="primary", key=f"approve-{selected['id']}"):
        selected["status"] = "Approved"
        repository.save_test_case(selected)
        st.success("Approved for execution.")
        st.rerun()
    if third.button("Reject", key=f"reject-{selected['id']}"):
        selected["status"] = "Rejected"
        repository.save_test_case(selected)
        st.rerun()
    if fourth.button("Regenerate selected", key=f"regen-{selected['id']}"):
        analysis = next((item["analysis"] for item in requirements if item["id"] == selected["requirement_id"]), {"acceptance_criteria": selected.get("expected_results", [])})
        try:
            with st.spinner("Regenerating the selected scenario…"):
                regenerated, mode = TestCaseAgent(settings.skills_dir, _provider(settings)).generate(selected["requirement_id"], analysis)
            selected_negative = bool(re.search(r"negative|validation|invalid", f"{selected.get('test_type', '')} {selected.get('title', '')}", re.I))
            replacement = next((case for case in regenerated if bool(re.search(r"negative|validation|invalid", f"{case.get('test_type', '')} {case.get('title', '')}", re.I)) == selected_negative), None)
            if not replacement:
                st.error("The generator returned no replacement case for the selected scenario type.")
            else:
                replacement.update({"id": selected["id"], "requirement_id": selected["requirement_id"], "status": "Draft"})
                repository.save_test_case(replacement)
                st.success(f"Regenerated selected case · {mode}; approval was reset.")
                st.rerun()
        except Exception as error:
            st.error(f"Regeneration failed: {error}")
    export_format = st.selectbox("Export format", ["JSON", "CSV", "Excel", "Markdown"])
    content, mime, filename = make_export(filtered, export_format)
    st.download_button("Download filtered cases", content, filename, mime)
    confirm_delete = st.checkbox("Confirm test case deletion", key=f"confirm-delete-case-{selected['id']}")
    if st.button("Delete selected case", key=f"delete-{selected['id']}", disabled=not confirm_delete):
        repository.delete_test_case(selected["id"])
        log_event(logging.getLogger("ui_automation"), "TestCaseAgent", "test_case_deleted", test_case_id=selected["id"])
        st.success("Deleted test case.")
        st.rerun()


def _locators(repository: Repository, settings: Settings, logger: logging.Logger) -> None:
    _title("04 / Live DOM", "Find elements", "Enter the website and optional sign-in details once. Discovery runs for the selected story and shares its saved elements across that story’s cases.")
    requirements = repository.requirements()
    if not requirements:
        st.info("Analyze a user story before finding its page elements.")
        return
    requirement = st.selectbox("User story", requirements, format_func=lambda item: f"{item['id']} · {item['title']}")
    cases = [case for case in repository.test_cases() if case.get("requirement_id") == requirement["id"]]
    target = repository.requirement_target(requirement["id"]) or {}
    session_auth = st.session_state.get("requirement_credentials", {}).get(requirement["id"], {})
    with st.form(f"find-elements-{requirement['id']}"):
        target_url = st.text_input("Website URL", value=target.get("application_url") or settings.target_url, placeholder="https://qa.example.com", key=f"locator-url-{requirement['id']}")
        auth_options = ["No Authentication", "Username & Password"]
        auth_value = target.get("authentication_type", settings.authentication_type or "No Authentication")
        auth_index = auth_options.index(auth_value) if auth_value in auth_options else 0
        authentication_type = st.selectbox("Sign-in", auth_options, index=auth_index, key=f"locator-auth-{requirement['id']}")
        username = password = username_label = password_label = submit_label = ""
        if authentication_type == "Username & Password":
            username = st.text_input("Username", value=session_auth.get("username", settings.target_username), key=f"locator-username-{requirement['id']}")
            password = st.text_input("Password", value=session_auth.get("password", settings.target_password), type="password", key=f"locator-password-{requirement['id']}")
            username_label = st.text_input("Username field label (optional)", value=target.get("username_label", settings.username_label), key=f"locator-username-label-{requirement['id']}")
            password_label = st.text_input("Password field label (optional)", value=target.get("password_label", settings.password_label), key=f"locator-password-label-{requirement['id']}")
            submit_label = st.text_input("Sign-in button label (optional)", value=target.get("submit_label", settings.submit_label), key=f"locator-submit-label-{requirement['id']}")
        browser_options = ["chromium", "firefox", "webkit"]
        current_browser = target.get("browser") or (settings.browser if settings.browser in browser_options else "chromium")
        browser_index = browser_options.index(current_browser) if current_browser in browser_options else 0
        browser = st.selectbox("Browser", browser_options, index=browser_index, key=f"locator-browser-{requirement['id']}")
        execution_mode = st.selectbox("Execution mode", ["headless", "headed"], index=0 if target.get("headless", settings.headless) else 1, key=f"locator-mode-{requirement['id']}")
        guidance = st.text_area("Additional guidance (optional)", value=target.get("guidance", ""), placeholder="For example: focus on account access, primary navigation, and record actions.", height=90, key=f"locator-guidance-{requirement['id']}")
        discover = st.form_submit_button("Find elements across all story cases", type="primary", disabled=not bool(cases))
    if not cases:
        st.info("Generate test cases for this story first. Discovery will scan the page once and share the saved elements across all of them.")
    st.caption(f"{len(cases)} test case(s) will use this story’s shared element repository.")
    if discover:
        try:
            parsed_url = urlsplit(target_url.strip())
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or parsed_url.username or parsed_url.password:
                raise ValueError("Enter a valid HTTP(S) website URL without embedded credentials.")
            if authentication_type == "Username & Password" and not (username.strip() and password):
                raise ValueError("Enter both a username and password, or choose No Authentication.")
            target_settings = {
                "requirement_id": requirement["id"],
                "application_url": target_url.strip(),
                "authentication_type": authentication_type,
                "browser": browser,
                "headless": execution_mode == "headless",
                "username_label": username_label.strip(),
                "password_label": password_label.strip(),
                "submit_label": submit_label.strip(),
                "guidance": guidance.strip(),
            }
            repository.save_requirement_target(target_settings)
            credentials = {"username": username.strip(), "password": password} if authentication_type == "Username & Password" else {}
            st.session_state.setdefault("requirement_credentials", {})[requirement["id"]] = credentials
            auth_details = {**target_settings, **credentials}
            log_event(logger, "LocatorAgent", "locator_discovery_started", requirement_id=requirement["id"], test_case_count=len(cases), browser=browser, target_url=target_url.strip())
            with st.spinner(f"Inspecting the page for {len(cases)} test cases…"):
                discovered = LocatorService(replace(settings, browser=browser, headless=target_settings["headless"])).discover(
                    target_url.strip(), browser, auth_details, guidance.strip()
                )
            for item in discovered:
                item["requirement_id"] = requirement["id"]
                item["test_case_id"] = None
            validated = [item for item in discovered if any(candidate.get("valid") for candidate in item.get("candidates", []))]
            for item in validated:
                repository.save_locator(item)
            st.session_state.setdefault("discovered_story_locators", {})[requirement["id"]] = discovered
            log_event(logger, "LocatorAgent", "locator_discovery_completed", requirement_id=requirement["id"], test_case_count=len(cases), element_count=len(discovered), saved_element_count=len(validated))
            st.success(f"Found {len(discovered)} elements; saved {len(validated)} validated elements for all {len(cases)} story cases.")
        except Exception as error:
            log_event(logger, "LocatorAgent", "locator_discovery_failed", level=logging.ERROR, requirement_id=requirement["id"], browser=browser, error=f"{type(error).__name__}: {error}")
            st.error(f"Element discovery failed: {error}")
            st.caption("Install the selected browser with `playwright install chromium` (or the chosen engine).")
    discovered = st.session_state.get("discovered_story_locators", {}).get(requirement["id"], [])
    if discovered:
        st.dataframe(pd.DataFrame([{"Element": item["element"], "Tag": item["tag"], "Validated": any(candidate.get("valid") for candidate in item["candidates"]), "Guidance matches": ", ".join(item.get("guidance_matches", []))} for item in discovered]), width="stretch", hide_index=True)
        for index, item in enumerate(discovered):
            with st.expander(f"{item['element']} · {item['tag']}", expanded=False):
                st.markdown(f"**Primary XPath**\n\n`{item['xpath']}`")
                st.dataframe(pd.DataFrame(item["candidates"]), width="stretch", hide_index=True, key=f"discovered-candidates-{requirement['id']}-{index}")
                st.caption(item["explanation"])
    saved = repository.locators(requirement_id=requirement["id"])
    if saved:
        st.subheader("Saved shared elements")
        st.dataframe(pd.DataFrame([{"Element": item["element"], "XPath": item["xpath"], "Validated": item["validated"], "Confidence": item["confidence"], "URL": item["page_url"]} for item in saved]), width="stretch", hide_index=True)


def _scripts(repository: Repository, settings: Settings, llm: LLMProvider, logger: logging.Logger) -> None:
    _title("05 / Script review", "Playwright scripts", "Choose a story and case; its shared validated elements are used for script generation.")
    requirements = repository.requirements()
    if not requirements:
        st.info("Generate a test case first.")
        return
    requirement = st.selectbox("User story", requirements, format_func=lambda item: f"{item['id']} · {item['title']}")
    target = repository.requirement_target(requirement["id"])
    if not target:
        st.warning("Find elements for this story first and save its website URL.")
        return
    cases = [case for case in repository.test_cases() if case.get("requirement_id") == requirement["id"]]
    if not cases:
        st.info("Generate a test case for this story first.")
        return
    case = st.selectbox("Test case", cases, format_func=lambda item: f"{item['id']} · {item['title']}")
    locators = repository.locators(case["id"], requirement["id"])
    st.caption(f"{sum(item['validated'] for item in locators)} validated locators available for this case.")
    if st.button("Generate script", type="primary"):
        try:
            log_event(logger, "ScriptAgent", "script_generation_started", requirement_id=requirement["id"], test_case_id=case["id"], locator_count=len(locators))
            with st.spinner("Generating and validating the Playwright script…"):
                source = PlaywrightScriptAgent(settings.skills_dir, llm).generate({**case, "target_url": target["application_url"], "browser": target["browser"], "headless": target["headless"], "authentication_type": target["authentication_type"], "username_label": target["username_label"], "password_label": target["password_label"], "submit_label": target["submit_label"]}, locators)
            st.session_state[f"script-{case['id']}"] = source
            log_event(logger, "ScriptAgent", "script_generation_completed", test_case_id=case["id"], script_line_count=len(source.splitlines()))
        except Exception as error:
            log_event(logger, "ScriptAgent", "script_generation_failed", level=logging.ERROR, test_case_id=case["id"], error=f"{type(error).__name__}: {error}")
            st.error(f"Script generation failed: {error}")
    source = st.text_area("Review and edit Python source", value=st.session_state.get(f"script-{case['id']}", repository.latest_script(case["id"]) or ""), height=430, key=f"script-editor-{case['id']}")
    try:
        ast.parse(source) if source.strip() else None
        syntax_valid = bool(source.strip())
    except SyntaxError as error:
        syntax_valid = False
        st.error(f"Syntax error at line {error.lineno}: {error.msg}")
    if source.strip() and syntax_valid:
        st.success("Python syntax is valid. This does not prove the script works or that the test passed.")
    col1, col2 = st.columns(2)
    if col1.button("Save reviewed script"):
        if not syntax_valid:
            st.error("Fix syntax errors before saving.")
        else:
            repository.save_script(case["id"], source)
            path = settings.scripts_dir / f"{case['id']}.py"
            path.write_text(source, encoding="utf-8")
            st.success("Script saved to history and the generated scripts folder.")
    col2.download_button("Download script", source, f"{case['id']}.py", "text/x-python", disabled=not source.strip())
    if source.strip():
        safe_source = json.dumps(source).replace("<", "\\u003c")
        components.html(
            f"""<button id="copy-script" style="font:600 14px 'DM Sans',sans-serif;padding:8px 14px;border:1px solid #007e72;border-radius:4px;background:#007e72;color:white;cursor:pointer">Copy script</button><span id="copy-status" style="margin-left:10px;color:#31564f"></span><script>document.getElementById('copy-script').addEventListener('click', async () => {{ try {{ await navigator.clipboard.writeText({safe_source}); document.getElementById('copy-status').textContent = 'Copied'; }} catch (error) {{ document.getElementById('copy-status').textContent = 'Clipboard unavailable in this browser'; }} }});</script>""",
            height=44,
        )
    if "TODO:" in source:
        st.warning("This script contains unmapped steps. Resolve every TODO and review actions before standalone use.")
    with st.expander("Copyable source"):
        st.code(source, language="python")


def _execution(repository: Repository, settings: Settings, logger: logging.Logger) -> None:
    _title("06 / Run", "Test execution", "Only approved cases execute. Each case is isolated so a failure does not stop the batch.")
    requirements = repository.requirements()
    if not requirements:
        st.info("Analyze a user story before executing its cases.")
        return
    requirement = st.selectbox("User story", requirements, format_func=lambda item: f"{item['id']} · {item['title']}")
    target_settings = repository.requirement_target(requirement["id"])
    if not target_settings:
        st.warning("Find elements for this story and save its website URL before executing cases.")
        return
    approved = [case for case in repository.test_cases() if case.get("requirement_id") == requirement["id"] and case.get("status") == "Approved"]
    if not approved:
        st.info("Approve one or more cases for this story before execution.")
        return
    target = target_settings["application_url"]
    browser = target_settings["browser"]
    st.caption(f"{target} · {browser} · {'headless' if target_settings['headless'] else 'headed'} · shared elements for {requirement['id']}")
    selected = st.multiselect("Approved test cases", approved, default=[], format_func=lambda item: f"{item['id']} · {item['title']}")
    col1, col2 = st.columns(2)
    run_selected = col1.button("Execute selected", type="primary", disabled=not selected)
    run_all = col2.button("Execute all approved", disabled=not approved)
    chosen = selected if run_selected else approved if run_all else []
    if chosen:
        run_id = f"RUN-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        repository.create_run(run_id, target, browser)
        log_event(logger, "ExecutionAgent", "execution_run_started", run_id=run_id, requirement_id=requirement["id"], browser=browser, headless=target_settings["headless"], selected_case_count=len(chosen))
        progress = st.progress(0, text="Preparing browser run")
        outcome_rows = []
        runtime_credentials = st.session_state.get("requirement_credentials", {}).get(requirement["id"], {})
        runtime_authentication = {**target_settings, **runtime_credentials}
        run_settings = replace(settings, browser=browser, headless=target_settings["headless"])
        for index, case in enumerate(chosen, 1):
            progress.progress((index - 1) / len(chosen), text=f"Running {case['id']} · {index}/{len(chosen)}")
            locators = repository.locators(case["id"], requirement["id"])
            outcome = ExecutionService(run_settings).run_case(case, run_id, locators, target, browser, authentication=runtime_authentication)
            repository.save_result(run_id, case["id"], outcome["status"], outcome["duration"], outcome["error"], outcome, outcome["steps"])
            outcome_rows.append(outcome)
            log_event(logger, "ExecutionAgent", "test_case_result_persisted", run_id=run_id, test_case_id=case["id"], status=outcome["status"], duration_seconds=outcome["duration"])
        summary = dict(Counter(item["status"] for item in outcome_rows))
        summary["total"] = len(outcome_rows)
        summary["duration"] = round(sum(item["duration"] for item in outcome_rows), 3)
        repository.finish_run(run_id, summary)
        log_event(logger, "ExecutionAgent", "execution_run_finished", run_id=run_id, requirement_id=requirement["id"], summary=summary)
        progress.progress(1.0, text=f"Run complete · {run_id}")
        st.session_state["last_run_id"] = run_id
        st.success(f"Run {run_id} completed · " + " · ".join(f"{key}: {value}" for key, value in summary.items()))
        for outcome in outcome_rows:
            _show_result(outcome)
    elif repository.history():
        st.caption(f"Latest persisted run: {repository.history()[0]['id']}")


def _show_result(outcome: dict[str, Any]) -> None:
    with st.expander(f"{outcome['test_case_id']} · {outcome['status']} · {outcome['duration']:.2f}s"):
        st.write(outcome.get("error") or "No test-level error.")
        rows = [{key: step.get(key) for key in ("step_number", "action", "expected", "actual", "status", "duration", "locator", "error", "page_url")} for step in outcome.get("steps", [])]
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        for step in outcome.get("steps", []):
            for path, label in ((step.get("before_screenshot_path"), "before"), (step.get("screenshot_path"), step["status"].lower())):
                if path and Path(path).exists():
                    st.image(path, caption=f"{outcome['test_case_id']} · step {step['step_number']} · {label}", width="stretch")


def _history(repository: Repository) -> None:
    _title("07 / Trace", "Execution history", "Every run, result, step, locator, exception, and screenshot remains inspectable.")
    runs = repository.history()
    if not runs:
        st.info("No historical runs yet.")
        return
    run = st.selectbox("Execution run", runs, format_func=lambda item: f"{item['id']} · {item['started_at']} · {item['status']}")
    st.json(run["summary"])
    results = repository.results(run["id"])
    for result in results:
        with st.expander(f"{result.get('test_case_id')} · {result.get('title')} · {result['status']} · {result['duration']:.2f}s"):
            st.write(result["error"] or "No test-level error.")
            steps = repository.step_results(result["id"])
            if steps:
                st.dataframe(pd.DataFrame(steps), width="stretch", hide_index=True)
                for step in steps:
                    for path, label in ((step.get("before_screenshot_path"), "before"), (step["screenshot_path"], step["status"].lower())):
                        if path and Path(path).exists():
                            st.image(path, caption=f"Step {step['step_number']} · {label}", width="stretch")
            details = json.loads(result["details"])
            if details:
                with st.expander("Execution context"):
                    st.json({key: value for key, value in details.items() if key != "steps"})


def _reporting(repository: Repository) -> None:
    _title("08 / Outcomes", "Reporting", "Actionable results from persisted executions, not generated plans.")
    runs = repository.history()
    results = repository.results()
    if not results:
        st.info("The dashboard will populate after the first test run.")
        return
    frame = pd.DataFrame(results)
    run_options = ["All runs"] + [item["id"] for item in runs]
    run_filter = st.selectbox("Execution run filter", run_options)
    if run_filter != "All runs":
        frame = frame[frame["run_id"] == run_filter]
    filter_columns = st.columns(3)
    for column, field, label in (
        (filter_columns[0], "requirement_id", "Requirement"),
        (filter_columns[1], "priority", "Priority"),
        (filter_columns[2], "test_type", "Test type"),
        (filter_columns[0], "status", "Status"),
        (filter_columns[1], "browser", "Browser"),
    ):
        values = ["All"] + sorted(str(value) for value in frame[field].dropna().unique()) if field in frame else ["All"]
        selected_value = column.selectbox(label, values, key=f"report-filter-{field}")
        if selected_value != "All" and field in frame:
            frame = frame[frame[field].astype(str) == selected_value]
    date_values = pd.to_datetime(frame["run_started_at"], errors="coerce", utc=True).dropna() if "run_started_at" in frame else pd.Series(dtype="datetime64[ns, UTC]")
    if not date_values.empty:
        date_col1, date_col2 = st.columns(2)
        start_date = date_col1.date_input("From date", value=date_values.min().date(), key="report-start-date")
        end_date = date_col2.date_input("To date", value=date_values.max().date(), key="report-end-date")
        run_dates = pd.to_datetime(frame["run_started_at"], errors="coerce", utc=True).dt.date
        frame = frame[(run_dates >= start_date) & (run_dates <= end_date)]
    if frame.empty:
        st.info("No execution results match these filters.")
        return
    cols = st.columns(5)
    counts = frame["status"].value_counts().to_dict()
    total = len(frame)
    executed = counts.get("PASS", 0) + counts.get("FAIL", 0)
    cols[0].metric("Total", total)
    cols[1].metric("Passed", counts.get("PASS", 0))
    cols[2].metric("Failed", counts.get("FAIL", 0))
    cols[3].metric("Blocked", counts.get("BLOCKED", 0))
    cols[4].metric("Pass rate", f"{counts.get('PASS', 0) / executed:.0%}" if executed else "—")
    left, right = st.columns(2)
    left.subheader("Status distribution")
    left.bar_chart(pd.DataFrame({"Test cases": pd.Series(counts)}))
    right.subheader("Outcomes by priority")
    priority_table = pd.crosstab(frame["priority"].fillna("Unknown"), frame["status"])
    right.bar_chart(priority_table)
    st.subheader("Result details")
    columns = ["run_id", "test_case_id", "title", "requirement_id", "priority", "test_type", "status", "duration", "browser", "run_started_at"]
    st.dataframe(frame[columns], width="stretch", hide_index=True)
    step_counts = Counter()
    for result in repository.results(run_filter if run_filter != "All runs" else None):
        step_counts.update(step["status"] for step in repository.step_results(result["id"]))
    if step_counts:
        st.subheader("Step-level outcomes")
        st.bar_chart(pd.DataFrame({"Steps": pd.Series(dict(step_counts))}))
    if runs:
        st.subheader("Execution trend")
        trend = pd.DataFrame([{ "Run": run["id"], "Started": run["started_at"], **run["summary"] } for run in reversed(runs)])
        for status in ("PASS", "FAIL", "BLOCKED", "SKIPPED"):
            if status not in trend:
                trend[status] = 0
        st.line_chart(trend.set_index("Started")[["PASS", "FAIL", "BLOCKED", "SKIPPED"]].fillna(0))
    st.download_button("Download filtered report JSON", frame.to_json(orient="records", indent=2), "execution-report.json", "application/json")
    if runs:
        latest = runs[0]
        archive_results = []
        for row in repository.results(latest["id"]):
            archive_results.append({**row, "steps": repository.step_results(row["id"])})
        scripts = {case["id"]: repository.latest_script(case["id"]) for case in repository.test_cases() if repository.latest_script(case["id"])}
        st.download_button("Download latest run evidence ZIP", evidence_archive(archive_results, scripts, repository.locators()), f"{latest['id']}-evidence.zip", "application/zip")


def _settings(settings: Settings, llm: LLMProvider) -> None:
    _title("Workspace / Config", "Settings", "Credentials are kept in process memory in this form and are never written to the database.")
    st.subheader("LLM provider")
    configured_provider = st.session_state.get("llm_provider", settings.llm_provider)
    provider = st.selectbox("Provider", ["openai_compatible", "anthropic"], index=1 if configured_provider == "anthropic" else 0)
    default_base_url = "https://api.anthropic.com/v1" if provider == "anthropic" else settings.llm_base_url
    saved_base_url = st.session_state.get("llm_base_url") if st.session_state.get("llm_provider") == provider else default_base_url
    base_url = st.text_input("Provider API base URL", saved_base_url or default_base_url)
    model = st.text_input("Model name", st.session_state.get("llm_model", settings.llm_model))
    api_key = st.text_input("API key", st.session_state.get("llm_api_key", settings.llm_api_key), type="password")
    if st.button("Apply for this session"):
        st.session_state["llm_provider"] = provider
        st.session_state["llm_base_url"] = base_url
        st.session_state["llm_model"] = model
        st.session_state["llm_api_key"] = api_key
        st.success("Provider settings applied to this Streamlit session only.")
        st.rerun()
    st.info("For persistent configuration, copy `.env.example` to `.env` and set LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL, and LLM_API_KEY. Supported adapters: OpenAI-compatible chat completions and Anthropic Messages API.")
    st.subheader("Browser and target")
    st.code(f"TARGET_URL={'configured' if settings.target_url else 'not configured'}\nBROWSER={settings.browser or 'not configured'}\nHEADLESS={'headless' if settings.mode_configured and settings.headless else 'headed' if settings.mode_configured else 'not configured'}\nTIMEOUT_MS={settings.timeout_ms}", language="text")
    st.caption(f"Database: {settings.database_path}\n\nEvidence: {settings.evidence_dir}")
    st.caption(f"Current LLM state: {'configured' if llm.configured else 'offline heuristic drafts only'}")
