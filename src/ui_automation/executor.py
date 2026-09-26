from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

from ui_automation.config import Settings
from ui_automation.locator_service import LocatorService
from ui_automation.utils import log_event


class ExecutionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = logging.getLogger("ui_automation.execution")

    def run_case(self, case: dict[str, Any], run_id: str, locators: list[dict[str, Any]], target_url: str, browser_name: str | None = None, authentication: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        result_id = str(uuid.uuid4())
        evidence_dir = self.settings.evidence_dir / run_id / case["id"]
        evidence_dir.mkdir(parents=True, exist_ok=True)
        step_results: list[dict[str, Any]] = []
        sensitive_masks: list[Any] = []
        overall = "PASS"
        error_summary = ""
        secrets = [str(authentication.get(key)) for key in ("username", "password") if authentication and authentication.get(key)]
        self._log("test_case_started", run_id, case["id"], browser=browser_name or self.settings.browser, target_url=self._safe_url(target_url))
        try:
            with sync_playwright() as playwright:
                self._log("browser_launch_started", run_id, case["id"], browser=browser_name or self.settings.browser or "chromium", headless=self.settings.headless)
                browser_choice = browser_name or self.settings.browser or "chromium"
                browser = getattr(playwright, browser_choice).launch(headless=self.settings.headless)
                page = browser.new_page()
                page.set_default_timeout(self.settings.timeout_ms)
                page.goto(target_url, wait_until="domcontentloaded")
                self._log("target_opened", run_id, case["id"], page_url=self._safe_url(page.url), page_title=self._redact(page.title(), secrets))
                sensitive_masks = [page.locator("input[type='password']")]
                if authentication and authentication.get("authentication_type") == "SSO":
                    raise RuntimeError("SSO execution requires a pre-authenticated browser session or an SSO-specific adapter.")
                tests_authentication = self._tests_authentication_flow(case)
                if authentication and authentication.get("authentication_type") == "Username & Password" and not tests_authentication:
                    self._log("authentication_started", run_id, case["id"], authentication_type="Username & Password")
                    username = authentication.get("username")
                    password = authentication.get("password")
                    if not username or not password:
                        raise RuntimeError("Username/password authentication is configured, but credentials are not available in this session.")
                    LocatorService._authenticate(page, authentication)
                    sensitive_masks.extend([page.locator("input, textarea"), page.get_by_text(str(username), exact=False), page.get_by_text(str(password), exact=False)])
                    self._log("authentication_completed", run_id, case["id"], authentication_type="Username & Password")
                for index, step in enumerate(case.get("steps", []), 1):
                    step_start = time.perf_counter()
                    started_at = datetime.now(timezone.utc).isoformat()
                    action = str(step.get("action", ""))
                    locator_requirement = str(step.get("locator_requirement", ""))
                    locator_entry = self._match_locator(action, locators, locator_requirement)
                    screenshot_path = ""
                    actual = ""
                    status = "PASS"
                    step_error = ""
                    before_screenshot_path = ""
                    locator_used = ""
                    locator = None
                    self._log("step_started", run_id, case["id"], step_number=index, step_id=f"{case['id']}-STEP-{index:03d}", step_action=self._redact(action, secrets), locator=self._redact(locator_entry.get("xpath", "") if locator_entry else "", secrets))
                    try:
                        if self.settings.screenshot_on_pass or self.settings.screenshot_on_failure:
                            before_path = evidence_dir / f"step-{index:02d}-before.png"
                            try:
                                page.screenshot(path=str(before_path), full_page=True, mask=sensitive_masks)
                                before_screenshot_path = str(before_path)
                            except PlaywrightError as error:
                                self._log("before_screenshot_failed", run_id, case["id"], step_number=index, error=self._redact(str(error), secrets), level=logging.WARNING)
                        if not locator_entry:
                            assertion_type = (step.get("assertion") or {}).get("type", "")
                            if assertion_type in {"text_visible", "text_absent", "url_contains", "title_contains"}:
                                actual = self._verify_step(page, None, step, action)
                            else:
                                status = "BLOCKED"
                                available = ", ".join(item.get("element", "") for item in locators if item.get("validated") or any(candidate.get("valid") for candidate in item.get("candidates", [])))
                                step_error = f"No validated locator matches '{locator_requirement or action}'. Available elements: {available or 'none'}"
                                actual = "Step was not executed."
                        else:
                            locator, locator_used, recovered = self._resolve_locator(page, locator_entry)
                            if locator is None:
                                status = "FAIL"
                                attempted = ", ".join(f"{candidate.get('kind')}={candidate.get('value')}" for candidate in locator_entry.get("candidates", []))
                                step_error = f"No saved locator candidate resolves uniquely and visibly. Tried: {attempted or locator_entry['xpath']}"
                            else:
                                test_data = self._runtime_test_data(step.get("test_data", ""), authentication)
                                self._perform_action(page, locator, action, test_data)
                                actual = self._verify_step(page, locator, {**step, "test_data": test_data}, action)
                                if recovered:
                                    actual += f" Recovered from the primary XPath using {locator_used}."
                    except (UnverifiedExpectation, UnsupportedAction) as error:
                        status = "BLOCKED"
                        step_error = str(error)
                        actual = "The action ran, but its expected outcome was not verified."
                    except Exception as error:
                        status = "FAIL"
                        step_error = f"{type(error).__name__}: {error}"
                        actual = "Action or assertion failed."
                    should_capture = (status == "PASS" and self.settings.screenshot_on_pass) or (status != "PASS" and self.settings.screenshot_on_failure)
                    if should_capture:
                        path = evidence_dir / f"step-{index:02d}-{status.lower()}.png"
                        try:
                            page.screenshot(path=str(path), full_page=True, mask=sensitive_masks)
                            screenshot_path = str(path)
                        except PlaywrightError as error:
                            self._log("screenshot_failed", run_id, case["id"], step_number=index, status=status, error=self._redact(str(error), secrets), level=logging.WARNING)
                    log_fields: dict[str, Any] = {
                        "step_number": index,
                        "step_id": f"{case['id']}-STEP-{index:03d}",
                        "status": status,
                        "duration_seconds": round(time.perf_counter() - step_start, 3),
                        "locator": self._redact(locator_used or (locator_entry.get("xpath", "") if locator_entry else ""), secrets),
                        "screenshot_path": screenshot_path,
                        "before_screenshot_path": before_screenshot_path,
                    }
                    if step_error:
                        log_fields["error"] = self._redact(step_error, secrets)
                    self._log("step_completed" if status == "PASS" else "step_failed", run_id, case["id"], level=logging.INFO if status == "PASS" else logging.WARNING, **log_fields)
                    step_results.append({"step_number": index, "action": action, "expected": step.get("expected_result", ""), "actual": actual, "status": status, "started_at": started_at, "ended_at": datetime.now(timezone.utc).isoformat(), "duration": round(time.perf_counter() - step_start, 3), "locator": locator_used if locator_entry and locator is not None else locator_entry.get("xpath", "") if locator_entry else "", "error": step_error, "screenshot_path": screenshot_path, "before_screenshot_path": before_screenshot_path, "page_url": page.url, "page_title": page.title()})
                    if status != "PASS":
                        overall = "BLOCKED" if status == "BLOCKED" and overall == "PASS" else "FAIL"
                        error_summary = step_error
                        if overall == "FAIL":
                            break
                if not step_results:
                    overall = "BLOCKED"
                    error_summary = "Test case has no executable steps."
                browser.close()
        except Exception as error:
            overall = "BLOCKED"
            error_summary = self._redact(f"{type(error).__name__}: {error}", secrets)
            self._log("execution_blocked", run_id, case["id"], level=logging.ERROR, error=error_summary, target_url=self._safe_url(target_url))
            if not step_results:
                step_results.append({"step_number": 0, "action": "Launch browser and open target", "expected": "Target application is reachable", "actual": "Execution could not start.", "status": "BLOCKED", "started_at": datetime.now(timezone.utc).isoformat(), "ended_at": datetime.now(timezone.utc).isoformat(), "duration": round(time.perf_counter() - started, 3), "locator": "", "error": error_summary, "screenshot_path": "", "page_url": target_url, "page_title": ""})
        error_summary = self._redact(error_summary, secrets)
        for step in step_results:
            for key, value in step.items():
                if isinstance(value, str):
                    step[key] = self._redact(value, secrets)
        duration = round(time.perf_counter() - started, 3)
        self._log("test_case_finished", run_id, case["id"], level=logging.INFO if overall == "PASS" else logging.WARNING, status=overall, duration_seconds=duration, step_count=len(step_results), error=error_summary or None)
        return {"id": result_id, "test_case_id": case["id"], "status": overall, "duration": duration, "error": error_summary, "steps": step_results}

    def _log(self, action: str, run_id: str, test_case_id: str, *, level: int = logging.INFO, **fields: Any) -> None:
        log_event(self.logger, "ExecutionAgent", action, level=level, run_id=run_id, test_case_id=test_case_id, **fields)

    @staticmethod
    def _safe_url(url: str) -> str:
        try:
            parts = urlsplit(url)
            if parts.scheme and parts.hostname:
                host = parts.hostname + (f":{parts.port}" if parts.port else "")
                return f"{parts.scheme}://{host}"
        except ValueError:
            return "[invalid-url]"
        return "[non-http-url]"

    @staticmethod
    def _redact(value: str, secrets: list[str]) -> str:
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"https?://[^\s\"'<>]+", lambda match: ExecutionService._safe_url(match.group(0)), value)
        return value

    @staticmethod
    def _match_locator(action: str, locators: list[dict[str, Any]], locator_requirement: str = "") -> dict[str, Any] | None:
        stop_words = {"the", "a", "an", "to", "be", "able", "should", "user", "verify", "verification", "acceptance", "criterion", "criteria", "identify", "relevant", "control", "target", "application", "on", "this", "for", "with", "enter", "fill", "type", "input", "field", "element"}
        aliases = {
            "login": {"login", "log", "in", "signin", "sign", "authenticate", "submit"},
            "username": {"username", "user", "userid", "email", "identifier", "account"},
            "identifier": {"username", "user", "userid", "email"},
            "password": {"password", "passcode", "secret"},
            "secret": {"password", "passcode"},
            "submit": {"submit", "login", "signin", "sign", "authenticate"},
        }
        requested_terms = set(re.findall(r"[a-z0-9]+", f"{action} {locator_requirement}".lower())) - stop_words
        expanded_terms = set(requested_terms)
        for term in requested_terms:
            expanded_terms.update(aliases.get(term, ()))
        matches: list[tuple[int, int, dict[str, Any]]] = []
        for item in locators:
            has_valid_candidate = any(candidate.get("valid") for candidate in item.get("candidates", []))
            if not has_valid_candidate and not item.get("validated"):
                continue
            label = " ".join((item.get("element", ""), item.get("tag", ""), item.get("xpath", "")))
            label_terms = set(re.findall(r"[a-z0-9]+", label.lower()))
            overlap = len(requested_terms & label_terms) + 2 * len((expanded_terms - requested_terms) & label_terms)
            if overlap:
                matches.append((overlap, -len(label_terms), item))
        return max(matches, key=lambda match: (match[0], match[1]), default=(0, 0, None))[2]

    @staticmethod
    def _tests_authentication_flow(case: dict[str, Any]) -> bool:
        context = " ".join([
            str(case.get("title", "")),
            *(str(step.get("action", "")) + " " + str(step.get("locator_requirement", "")) for step in case.get("steps", [])),
        ])
        return bool(re.search(r"login|log\s*in|sign\s*in|credential|authentication|username.{0,40}password|account.{0,40}(?:identifier|secret)|identifier.{0,40}secret", context, re.I))

    @staticmethod
    def _runtime_test_data(value: Any, authentication: dict[str, Any] | None) -> str:
        result = str(value or "")
        if authentication:
            result = result.replace("{{username}}", str(authentication.get("username") or ""))
            result = result.replace("{{password}}", str(authentication.get("password") or ""))
        return result

    @staticmethod
    def _resolve_locator(page: Any, entry: dict[str, Any]) -> tuple[Any | None, str, bool]:
        candidates = list(entry.get("candidates", []))
        primary_xpath = entry.get("xpath", "")
        xpath_candidate = next((candidate for candidate in candidates if candidate.get("kind") == "xpath"), None)
        if xpath_candidate and primary_xpath:
            xpath_candidate["value"] = primary_xpath
            xpath_candidate["valid"] = bool(entry.get("validated", xpath_candidate.get("valid", False)))
        elif primary_xpath:
            candidates.insert(0, {"kind": "xpath", "value": entry.get("xpath", ""), "valid": entry.get("validated", False)})
        priority = {"xpath": 0, "xpath_absolute": 1}
        candidates.sort(key=lambda candidate: (priority.get(candidate.get("kind"), 2), not candidate.get("valid", False)))
        for index, candidate in enumerate(candidates):
            if not candidate.get("valid") or not candidate.get("value"):
                continue
            kind, value = candidate["kind"], candidate["value"]
            try:
                locator = LocatorService._playwright_locator(page, kind, value)
            except ValueError:
                continue
            try:
                if locator.count() == 1 and locator.is_visible():
                    description = f"{kind}={value}"
                    return locator, description, index > 0
            except PlaywrightError:
                continue
        return None, "", False

    @staticmethod
    def _perform_action(page: Any, locator: Any, action: str, test_data: Any) -> None:
        lowered = action.lower()
        value = str(test_data or "")
        if any(word in lowered for word in ("enter", "fill", "type", "input")):
            locator.fill(value)
        elif any(word in lowered for word in ("select",)):
            locator.select_option(label=value if value else None)
        elif re.match(r"^\s*uncheck\b", lowered):
            locator.uncheck()
        elif re.match(r"^\s*check\b", lowered):
            locator.check()
        elif any(word in lowered for word in ("click", "submit", "save", "navigate", "open")):
            locator.click()
        elif any(word in lowered for word in ("verify", "assert", "visible", "display")):
            expect(locator).to_be_visible()
        else:
            raise UnsupportedAction("Unsupported action. Edit the step to use a supported fill, select, check, click, or visibility verification action.")

    @staticmethod
    def _verify_step(page: Any, locator: Any, step: dict[str, Any], action: str) -> str:
        assertion = step.get("assertion") or {}
        assertion_type = assertion.get("type", "")
        value = str(assertion.get("value", ""))
        if assertion_type == "text_visible":
            expect(page.get_by_text(value, exact=bool(assertion.get("exact", True)))).to_be_visible()
        elif assertion_type == "validation_visible":
            validation_feedback = page.locator("[role='alert'], [aria-live='assertive'], [data-test*='error'], [id*='error'], [class*='error'], [class*='validation'], [aria-invalid='true']")
            if not any(validation_feedback.nth(index).is_visible() for index in range(validation_feedback.count())):
                raise AssertionError("No visible validation feedback was found.")
        elif assertion_type == "text_absent":
            expect(page.get_by_text(value, exact=bool(assertion.get("exact", True)))).to_have_count(0)
        elif assertion_type == "element_visible":
            expect(locator).to_be_visible()
        elif assertion_type == "element_value":
            actual = locator.input_value()
            if actual != value:
                raise AssertionError(f"Expected input value {value!r}; found {actual!r}.")
        elif assertion_type == "url_contains":
            if value not in page.url:
                raise AssertionError(f"Expected URL to contain {value!r}; current URL is {page.url!r}.")
        elif assertion_type == "title_contains":
            if value not in page.title():
                raise AssertionError(f"Expected page title to contain {value!r}; found {page.title()!r}.")
        elif assertion_type == "checked":
            expect(locator).to_be_checked()
        elif assertion_type == "not_visible":
            expect(locator).to_be_hidden()
        elif assertion_type:
            raise UnverifiedExpectation(f"Unsupported assertion type: {assertion_type}")
        elif any(word in action.lower() for word in ("verify", "assert", "visible", "display")):
            expect(locator).to_be_visible()
        elif any(word in action.lower() for word in ("fill", "enter", "type", "input")):
            expected = str(step.get("test_data", ""))
            actual = locator.input_value()
            if actual != expected:
                raise AssertionError(f"Expected input value {expected!r}; found {actual!r}.")
        elif "check" in action.lower() or "uncheck" in action.lower():
            expect(locator).to_be_checked() if "uncheck" not in action.lower() else expect(locator).not_to_be_checked()
        else:
            raise UnverifiedExpectation("No executable assertion is defined. Add an assertion object such as {'type': 'text_visible', 'value': 'Saved successfully'}.")
        return "Action and expected outcome were verified."


class UnverifiedExpectation(RuntimeError):
    pass


class UnsupportedAction(RuntimeError):
    pass
