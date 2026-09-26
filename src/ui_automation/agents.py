from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ui_automation.documents import extract_application_details, redact_credentials
from ui_automation.llm import LLMError, LLMProvider


class SkillAgent:
    skill_name = ""

    def __init__(self, skills_dir: Path, llm: LLMProvider) -> None:
        self.skills_dir = skills_dir
        self.llm = llm

    def skill(self) -> str:
        path = self.skills_dir / self.skill_name / "skill.md"
        if not path.exists():
            raise FileNotFoundError(f"Required agent skill is missing: {path}")
        return path.read_text(encoding="utf-8")


class RequirementAgent(SkillAgent):
    skill_name = "requirement_analysis"

    def analyze_documents(self, documents: list[tuple[str, str]]) -> tuple[dict[str, Any], dict[str, Any], str]:
        combined = "\n\n".join(f"--- Uploaded file: {name} ---\n{text}" for name, text in documents)
        application = extract_application_details(combined)
        safe_text = redact_credentials(combined)
        prompt = json.dumps({"uploaded_documents": safe_text})
        if self.llm.configured:
            result = self.llm.complete_json(system=self.skill(), user=prompt)
            result.setdefault("user_story", "")
            result.setdefault("acceptance_criteria", [])
            result.setdefault("business_rules", [])
            result.setdefault("scenarios", {"positive": [], "negative": [], "boundary": []})
            result.setdefault("test_data_requirements", [])
            result.setdefault("automation_gaps", [])
            result.setdefault("ambiguities", [])
            result["application_details"] = {key: value for key, value in application.items() if key not in {"username", "password"}}
            return result, application, "LLM-assisted (credentials excluded from prompt)"

        story_match = re.search(r"(?im)^.*\bAs\s+(?:a|an|the)\s+.+?(?:\r?\n(?:.{0,4}\S.*)?){0,2}", safe_text)
        story = "\n".join(line.strip() for line in story_match.group(0).splitlines()).strip() if story_match else ""
        criteria = extract_criteria(safe_text)
        business_rules = [line for line in criteria if re.search(r"must|shall|required|mandatory|only|cannot|cannot|unique|maximum|minimum", line, re.I)]
        positive = [line for line in criteria if not re.search(r"invalid|error|reject|must not|cannot|mandatory|required", line, re.I)]
        negative = [line for line in criteria if re.search(r"invalid|error|reject|must not|cannot|mandatory|required", line, re.I)]
        ambiguity = []
        if not story:
            ambiguity.append("A user story could not be confidently identified in the uploaded documents.")
        if not criteria:
            ambiguity.append("Acceptance criteria could not be confidently identified in the uploaded documents.")
        analysis = {
            "user_story": story,
            "acceptance_criteria": criteria,
            "business_rules": business_rules,
            "scenarios": {"positive": positive, "negative": negative, "boundary": []},
            "test_data_requirements": extract_test_data(safe_text),
            "dependencies": [],
            "expected_ui_behavior": [],
            "automation_gaps": [],
            "ambiguities": ambiguity,
            "analysis_mode": "Offline heuristic extraction; no LLM call was made.",
        }
        analysis["application_details"] = {key: value for key, value in application.items() if key not in {"username", "password"}}
        return analysis, application, "Offline heuristic extraction"


class TestCaseAgent(SkillAgent):
    skill_name = "test_case_generation"

    def generate(self, requirement_id: str, analysis: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        if self.llm.configured:
            result = self.llm.complete_json(system=self.skill(), user=json.dumps({"requirement_id": requirement_id, "analysis": analysis}))
            cases = result.get("test_cases", [])
            normalized = [normalize_case(case, requirement_id, index) for index, case in enumerate(cases, 1)]
            limited = _limit_story_cases(normalized)
            _populate_step_test_data(limited, analysis)
            return limited, "LLM-assisted"

        criteria = [str(item).strip() for item in analysis.get("acceptance_criteria", []) if str(item).strip()]
        if not criteria:
            return [], "Offline heuristic draft"
        negative_pattern = re.compile(r"invalid|error|reject|must not|cannot|empty|missing|locked|not allowed|denied", re.I)
        negative_criteria = [criterion for criterion in criteria if negative_pattern.search(criterion) or re.search(r"mandatory|required", criterion, re.I)]
        positive_criteria = [criterion for criterion in criteria if not negative_pattern.search(criterion)]
        positive_steps = _scenario_steps(positive_criteria, negative=False)
        positive_case = {
            "id": "TC-001", "requirement_id": requirement_id,
            "title": "Verify positive acceptance criteria", "test_type": "Functional / Positive",
            "priority": "High", "status": "Draft", "preconditions": [],
            "test_data": {}, "expected_results": positive_criteria, "postconditions": [], "steps": positive_steps,
            "generation_note": "Offline heuristic draft: review the generated samples and confirm each locator before execution.",
        }
        cases = [positive_case]
        if negative_criteria:
            cases.append({
                "id": "TC-002", "requirement_id": requirement_id,
                "title": "Verify negative validation scenarios", "test_type": "Validation / Negative",
                "priority": "High", "status": "Draft", "preconditions": [],
                "test_data": {"invalid_or_missing_value": ""},
                "expected_results": [f"The application rejects invalid or missing input: {criterion}" for criterion in negative_criteria],
                "postconditions": [],
                "steps": _scenario_steps(negative_criteria, negative=True),
                "generation_note": "Offline heuristic draft: confirm that these negative scenarios match the intended UI.",
            })
        _populate_step_test_data(cases, analysis)
        return cases, "Offline heuristic draft"


class TestCaseReviewAgent(SkillAgent):
    skill_name = "test_case_review"

    def review(self, case: dict[str, Any], criteria: list[str]) -> list[str]:
        issues: list[str] = []
        for field in ("id", "title", "requirement_id", "test_type", "priority", "steps"):
            if not case.get(field):
                issues.append(f"Missing required field: {field}")
        if not isinstance(case.get("steps"), list) or not case.get("steps"):
            issues.append("At least one test step is required.")
        covered = " ".join(str(item) for item in case.get("expected_results", []))
        if criteria and not any(item.lower() in covered.lower() or covered.lower() in item.lower() for item in criteria if item):
            issues.append("Expected results do not clearly trace to an acceptance criterion; confirm traceability.")
        return issues


class PlaywrightScriptAgent(SkillAgent):
    skill_name = "playwright_script_generation"

    def generate(self, case: dict[str, Any], locators: list[dict[str, Any]]) -> str:
        self.skill()
        target_url = case.get("target_url")
        if not target_url:
            raise ValueError("A saved application environment profile with a URL is required before script generation.")
        if case.get("authentication_type") == "SSO":
            raise ValueError("Standalone SSO script generation requires a configured SSO adapter or pre-authenticated storage state.")
        locator_map = {
            re.sub(r"[^a-z0-9]+", "", item["element"].lower()): item
            for item in locators
            if item.get("validated") or any(candidate.get("valid") for candidate in item.get("candidates", []))
        }
        test_name = re.sub(r"[^a-z0-9]+", "_", case["id"].lower()).strip("_")
        tests_authentication = _case_tests_authentication(case)
        lines = [
            "import logging", "import os", "import re", "from pathlib import Path", "from playwright.sync_api import expect, sync_playwright",
            "", "logging.basicConfig(level=logging.INFO)", "logger = logging.getLogger(__name__)",
            "", "def resolve_locator(page, candidates):",
            "    for candidate in candidates:",
            "        kind, value = candidate['kind'], candidate['value']",
            "        if kind in ('xpath', 'xpath_absolute'): locator = page.locator('xpath=' + value)",
            "        elif kind == 'test_id': locator = page.get_by_test_id(value)",
            "        elif kind == 'id': locator = page.locator(page.evaluate(\"id => '#' + CSS.escape(id)\", value))",
            "        elif kind == 'role':",
            "            role, name = value.split(': ', 1)",
            "            locator = page.get_by_role(role, name=name, exact=True)",
            "        elif kind == 'label': locator = page.get_by_label(value, exact=True)",
            "        elif kind == 'placeholder': locator = page.get_by_placeholder(value, exact=True)",
            "        elif kind == 'text': locator = page.get_by_text(value, exact=True)",
            "        elif kind == 'css': locator = page.locator(value)",
            "        else: continue",
            "        try:",
            "            if locator.count() == 1 and locator.is_visible(): return locator",
            "        except Exception:",
            "            continue",
            "    raise LookupError('No validated XPath or alternative locator resolves uniquely and visibly')",
            "", f"def run_{test_name}() -> None:", "    evidence = Path('evidence') / " + json.dumps(case["id"]),
            "    evidence.mkdir(parents=True, exist_ok=True)", "    with sync_playwright() as playwright:",
            f"        browser = playwright.{case.get('browser', 'chromium')}.launch(headless={bool(case.get('headless', True))})", "        page = browser.new_page()",
            "        page.set_default_timeout(10000)", "        try:",
            f"            page.goto({json.dumps(target_url)})",
        ]
        if case.get("authentication_type") == "Username & Password":
            lines.extend([
                "            username = os.environ.get('UI_AUTOMATION_USERNAME')",
                "            password = os.environ.get('UI_AUTOMATION_PASSWORD')",
                "            if not username or not password:",
                "                raise RuntimeError('Set UI_AUTOMATION_USERNAME and UI_AUTOMATION_PASSWORD in the process environment')",
            ])
            if tests_authentication:
                lines.append("            sensitive_masks = [page.locator('input, textarea'), page.get_by_text(username, exact=False), page.get_by_text(password, exact=False)]")
            else:
                lines.extend([
                    f"            username_field = page.get_by_label({json.dumps(case.get('username_label', ''))}, exact=True) if {bool(case.get('username_label'))!r} else page.locator(\"input[autocomplete='username'], input[type='email'], input:not([type='password']):not([type='hidden']):not([type='submit'])\").first",
                    f"            password_field = page.get_by_label({json.dumps(case.get('password_label', ''))}, exact=True) if {bool(case.get('password_label'))!r} else page.locator(\"input[type='password']\").first",
                    f"            submit_button = page.get_by_role('button', name={json.dumps(case.get('submit_label', ''))}, exact=True) if {bool(case.get('submit_label'))!r} else page.get_by_role('button', name=re.compile(r'log\\s*in|sign\\s*in|submit|continue|next|verify|authenticate', re.I))",
                    "            assert username_field.count() == password_field.count() == submit_button.count() == 1, 'Sign-in controls must resolve uniquely'",
                    "            username_field.fill(username)",
                    "            password_field.fill(password)",
                    "            sensitive_masks = [page.locator('input, textarea'), username_field, password_field, page.get_by_text(username, exact=False), page.get_by_text(password, exact=False)]",
                    "            submit_button.click()",
                ])
        else:
            lines.append("            sensitive_masks = [page.locator(\"input[type='password']\")]")
        for step in case.get("steps", []):
            action = str(step.get("action", "")).lower()
            locator = _match_case_locator(action, str(step.get("locator_requirement", "")), list(locator_map.values()))
            step_number = step.get("number", "?")
            if locator:
                candidates = self._script_locator_candidates(locator)
                if not candidates:
                    lines.append(f"            raise LookupError({json.dumps('No validated locator candidates for step ' + str(step_number))})")
                    continue
                target = f"step_locator_{step_number}"
                lines.append(f"            {target} = resolve_locator(page, {json.dumps(candidates)})")
                lines.append(f"            logger.info({json.dumps('Step ' + str(step_number) + ': ' + step.get('action', ''))})")
                lines.append(f"            {target}.wait_for(state='visible')")
                raw_test_data = str(step.get("test_data", ""))
                test_data = {"{{username}}": "username", "{{password}}": "password"}.get(raw_test_data, json.dumps(raw_test_data))
                if any(word in action for word in ("enter", "fill", "type", "input")):
                    lines.append(f"            {target}.fill({test_data})")
                    lines.append(f"            assert {target}.input_value() == {test_data}")
                elif "select" in action:
                    lines.append(f"            {target}.select_option(label={test_data})")
                elif "check" in action and "uncheck" not in action:
                    lines.append(f"            {target}.check()")
                    lines.append(f"            expect({target}).to_be_checked()")
                elif "uncheck" in action:
                    lines.append(f"            {target}.uncheck()")
                    lines.append(f"            expect({target}).not_to_be_checked()")
                elif any(word in action for word in ("click", "submit", "save", "navigate", "open")):
                    lines.append(f"            {target}.click()")
                elif any(word in action for word in ("verify", "assert", "visible", "display")):
                    lines.append(f"            expect({target}).to_be_visible()")
                else:
                    lines.append(f"            raise NotImplementedError({json.dumps('Unsupported action for step ' + str(step_number))})")
                lines.extend(self._assertion_lines(step.get("assertion", {}), target, action))
            else:
                assertion = step.get("assertion", {})
                if assertion.get("type") in {"text_visible", "text_absent", "validation_visible", "url_contains", "title_contains"}:
                    lines.extend(self._assertion_lines(assertion, "None", action))
                else:
                    lines.append(f"            raise NotImplementedError({json.dumps('Step ' + str(step_number) + ' requires a validated locator mapping')})")
        lines.extend([
            "            page.screenshot(path=str(evidence / 'final-pass.png'), full_page=True, mask=sensitive_masks)",
            "        except Exception:",
            "            try:",
            "                page.screenshot(path=str(evidence / 'failure.png'), full_page=True, mask=sensitive_masks)",
            "            except Exception:",
            "                logger.exception('Failure screenshot could not be captured')",
            "            raise",
            "        finally:",
            "            browser.close()",
            "",
            "if __name__ == '__main__':",
            f"    run_{test_name}()",
        ])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _script_locator_candidates(entry: dict[str, Any]) -> list[dict[str, str]]:
        candidates = [
            {"kind": candidate["kind"], "value": str(candidate["value"])}
            for candidate in entry.get("candidates", [])
            if candidate.get("valid") and candidate.get("kind") and candidate.get("value")
        ]
        priority = {"xpath": 0, "xpath_absolute": 1}
        candidates.sort(key=lambda candidate: priority.get(candidate["kind"], 2))
        if not any(candidate["kind"] == "xpath" for candidate in candidates) and entry.get("validated") and entry.get("xpath"):
            candidates.insert(0, {"kind": "xpath", "value": str(entry["xpath"])})
        return candidates

    @staticmethod
    def _assertion_lines(assertion: dict[str, Any], locator: str, action: str) -> list[str]:
        assertion_type = assertion.get("type", "")
        value = json.dumps(str(assertion.get("value", "")))
        if assertion_type == "text_visible":
            return [f"            expect(page.get_by_text({value}, exact={bool(assertion.get('exact', True))})).to_be_visible()"]
        if assertion_type == "validation_visible":
            return [
                "            validation_feedback = page.locator(\"[role='alert'], [aria-live='assertive'], [data-test*='error'], [id*='error'], [class*='error'], [class*='validation'], [aria-invalid='true']\")",
                "            assert any(validation_feedback.nth(index).is_visible() for index in range(validation_feedback.count())), 'Expected visible validation feedback'",
            ]
        if assertion_type == "text_absent":
            return [f"            expect(page.get_by_text({value}, exact={bool(assertion.get('exact', True))})).to_have_count(0)"]
        if assertion_type == "element_visible":
            return [f"            expect({locator}).to_be_visible()"]
        if assertion_type == "element_value":
            return [f"            assert {locator}.input_value() == {value}"]
        if assertion_type == "url_contains":
            return [f"            assert {value} in page.url"]
        if assertion_type == "title_contains":
            return [f"            assert {value} in page.title()"]
        if assertion_type == "checked":
            return [f"            expect({locator}).to_be_checked()"]
        if assertion_type == "not_visible":
            return [f"            expect({locator}).to_be_hidden()"]
        if assertion_type:
            return [f"            raise NotImplementedError({json.dumps('Unsupported assertion type: ' + assertion_type)})"]
        if any(word in action for word in ("fill", "enter", "type", "input", "check", "uncheck", "verify", "assert", "visible", "display")):
            return []
        return ["            raise NotImplementedError('Add an explicit executable assertion for this action')"]


def extract_criteria(text: str) -> list[str]:
    items = []
    in_criteria = False
    for line in text.splitlines():
        if re.match(r"^\s*(?:web\s+application\s+url|application\s+url|url|authentication|username|user\s+name|password|passwd|environment|browser|execution\s+mode)\s*[:=|]", line, re.I):
            in_criteria = False
            continue
        heading = re.match(r"^\s*(?:#{1,6}\s*)?(acceptance\s+criteria|requirements|business\s+rules|test\s+data|scenarios)\s*:?[ \t]*$", line, re.I)
        if heading:
            in_criteria = heading.group(1).lower().startswith(("acceptance", "requirements", "business", "scenarios"))
            continue
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if in_criteria and cleaned and len(cleaned) > 12 and not re.match(r"^(?:as\s+(?:a|an)|user\s+story)\b", cleaned, re.I):
            items.append(cleaned)
    return items


def extract_test_data(text: str) -> list[str]:
    lines = text.splitlines()
    results = []
    collecting = False
    for line in lines:
        if re.match(r"^\s*(?:#{1,6}\s*)?test\s+data\b", line, re.I):
            collecting = True
            continue
        if collecting and re.match(r"^\s*(?:#{1,6}\s*)?[A-Za-z][A-Za-z ]{2,30}:\s*$", line):
            collecting = False
        if collecting and line.strip():
            results.append(re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip())
    return results


def normalize_case(case: dict[str, Any], requirement_id: str, index: int) -> dict[str, Any]:
    case.setdefault("id", f"TC-{index:03d}")
    case.setdefault("requirement_id", requirement_id)
    case.setdefault("status", "Draft")
    case.setdefault("preconditions", [])
    case.setdefault("test_data", {})
    case.setdefault("expected_results", [])
    case.setdefault("postconditions", [])
    case.setdefault("steps", [])
    for step_index, step in enumerate(case["steps"], 1):
        step.setdefault("number", step_index)
        step.setdefault("test_data", "")
        step.setdefault("expected_result", "")
        step.setdefault("locator_requirement", "")
        step.setdefault("automation_status", "Needs review")
        step.setdefault("assertion", {})
    return case


def _criterion_field(criterion: str) -> str:
    pattern = re.compile(
        r"^\s*(?:the\s+|a\s+|an\s+)?([A-Za-z][A-Za-z0-9 _-]{0,40}?)\s+(?:is|are|must be|should be)\s+(?:required|mandatory|optional|valid|unique|provided|entered|selected)",
        re.I,
    )
    match = pattern.search(criterion.strip().rstrip("."))
    if not match:
        return ""
    field = re.sub(r"^(?:a|an|the|valid|invalid)\s+", "", match.group(1).strip(), flags=re.I)
    return field[:1].upper() + field[1:]


def _scenario_steps(criteria: list[str], *, negative: bool) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []

    def add(action: str, locator_requirement: str, expected: str, test_data: str = "", assertion: dict[str, str] | None = None) -> None:
        steps.append({
            "number": len(steps) + 1,
            "action": action,
            "test_data": test_data,
            "expected_result": expected,
            "locator_requirement": locator_requirement,
            "automation_status": "Needs locator and action review",
            "assertion": assertion or {},
        })

    login_related = any(re.search(r"login|log\s*in|sign\s*in|credential|username|password|authentication|account identifier|account secret|passphrase", item, re.I) for item in criteria)
    if login_related:
        for criterion in criteria:
            lowered = criterion.lower()
            if re.search(r"enter|provide|input|type", lowered) and re.search(r"username|user name|account identifier|email", lowered) and re.search(r"password|passphrase|account secret", lowered):
                if negative:
                    add("Enter invalid account identifier", "Account identifier field", "Invalid account identifier is rejected.", "invalid-account")
                    add("Enter invalid account secret", "Account secret field", "Invalid account secret is rejected.", "InvalidSecret!234")
                    add("Submit sign-in form", "Sign-in submit control", "The invalid sign-in attempt is submitted.")
                else:
                    add("Enter account identifier", "Account identifier field", "Account identifier is entered.", "{{username}}")
                    add("Enter account secret", "Account secret field", "Account secret is entered.", "{{password}}")
            elif re.search(r"(?:click|press|select|activate).*button|(?:login|log\s*in|sign\s*in).*button|submit.*form", lowered):
                button_label = _button_label(criterion)
                if button_label:
                    add(f"Click {button_label} button", f"{button_label} button", "The sign-in form is submitted.")
                else:
                    add("Submit sign-in form", "Sign-in submit control", "The sign-in form is submitted.")
            elif re.search(r"empty|missing|required|mandatory", lowered) and re.search(r"username|user name|account identifier|email|password|passphrase|account secret", lowered):
                field = "Account identifier" if re.search(r"username|user name|account identifier|email", lowered) else "Account secret"
                other_field = "Account secret" if field == "Account identifier" else "Account identifier"
                if negative:
                    add(f"Fill {field} field with an empty value", f"{field} field", f"Missing {field.lower()} is rejected.")
                    add(f"Enter {other_field.lower()}", f"{other_field} field", f"{other_field} is entered.", "{{password}}" if other_field == "Account secret" else "{{username}}")
                    add("Submit sign-in form", "Sign-in submit control", "The incomplete sign-in attempt is submitted.")
            elif re.search(r"\bvalid credentials?\b|redirect|navigate|go to|success", lowered):
                destination = _destination_label(criterion)
                if not negative and destination:
                    add(f"Verify {destination} is displayed", f"{destination} page or heading", criterion, assertion={"type": "text_visible", "value": destination, "exact": False})
            elif re.search(r"invalid|error|reject|locked|not allowed|denied", lowered):
                if negative:
                    if re.search(r"locked|suspended|disabled", lowered):
                        add("Enter disabled-account identifier", "Account identifier field", "Disabled account is identified.", "disabled-test-account")
                        add("Enter account secret", "Account secret field", "Account secret is entered.", "{{password}}")
                        add("Submit sign-in form", "Sign-in submit control", "The disabled-account attempt is submitted.")
                    elif re.search(r"credential", lowered):
                        add("Enter invalid account identifier", "Account identifier field", "Invalid account identifier is rejected.", "invalid-account")
                        add("Enter invalid account secret", "Account secret field", "Invalid account secret is rejected.", "InvalidSecret!234")
                        add("Submit sign-in form", "Sign-in submit control", "The invalid sign-in attempt is submitted.")
                    add("Verify login error message", "", criterion, assertion={"type": "validation_visible"})
        if steps:
            for index, step in enumerate(steps):
                if not re.search(r"click.*button|submit.*form|sign-in", step["action"], re.I) or step.get("assertion"):
                    continue
                following_assertion = next((item.get("assertion") for item in steps[index + 1:] if item.get("assertion")), None)
                if following_assertion:
                    step["assertion"] = dict(following_assertion)
            return steps

    for criterion in criteria:
        field = _criterion_field(criterion)
        if negative and field:
            add(f"Leave {field} field empty", f"{field} field", criterion)
            add("Click Submit button", "Submit button", "The form is submitted for validation.")
            add("Verify validation message", "", criterion, assertion={"type": "validation_visible"})
        elif field:
            add(f"Enter valid {field} value", f"{field} field", criterion)
        else:
            add(f"Verify acceptance criterion: {criterion}", field or "", criterion)
    return steps


def _destination_label(criterion: str) -> str:
    cleaned = re.sub(r"[*_`#]", "", criterion).strip().rstrip(".!?")
    match = re.search(r"\b(?:to|into|onto)\s+(?:the\s+)?(.+?)\s+(?:page|screen|dashboard|workspace)\b", cleaned, re.I)
    return match.group(1).strip(" \"'“”") if match else ""


def _button_label(criterion: str) -> str:
    cleaned = re.sub(r"[*_`#]", "", criterion).strip()
    match = re.search(r"(?:click|press|select|activate)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9 _-]{0,30}?)\s+button\b", cleaned, re.I)
    return match.group(1).strip() if match else ""


def _populate_step_test_data(cases: list[dict[str, Any]], analysis: dict[str, Any]) -> None:
    hints = [str(item) for item in analysis.get("test_data_requirements", []) if str(item).strip()]
    for case in cases:
        negative = bool(re.search(r"negative|validation|invalid|missing|reject", f"{case.get('test_type', '')} {case.get('title', '')}", re.I))
        case_data = case.get("test_data") if isinstance(case.get("test_data"), dict) else {}
        generated_data = dict(case_data)
        for index, step in enumerate(case.get("steps", []), 1):
            current = step.get("test_data")
            if current not in (None, ""):
                generated_data.setdefault(f"step_{step.get('number', index)}", current)
                continue
            action = str(step.get("action", ""))
            if not re.search(r"fill|enter|type|input|select|choose|search|leave|invalid|missing|empty", action, re.I):
                continue
            context = " ".join((
                str(case.get("title", "")), str(case.get("test_type", "")), action,
                str(step.get("expected_result", "")), str(step.get("locator_requirement", "")),
                " ".join(hints),
            ))
            value = _synthetic_test_value(context, negative, action)
            step["test_data"] = value
            generated_data[f"step_{step.get('number', index)}"] = value
        case["test_data"] = generated_data


def _synthetic_test_value(context: str, negative: bool, action: str) -> str:
    lowered = context.lower()
    action_lower = action.lower()
    if not negative and re.search(r"username|user name|login id", lowered):
        return "{{username}}"
    if not negative and re.search(r"password", lowered):
        return "{{password}}"
    if negative and re.search(r"leave|missing|empty|blank|not provided", action_lower):
        return ""
    if negative:
        if re.search(r"email|e-mail", lowered):
            return "invalid-email"
        if re.search(r"url|website|web address", lowered):
            return "not-a-url"
        if re.search(r"date", lowered):
            return "not-a-date"
        if re.search(r"phone|telephone", lowered):
            return "abc123"
        if re.search(r"quantity|count|amount|price|age|number|numeric", lowered):
            return "not-a-number"
        if re.search(r"select|dropdown|option|status", lowered):
            return "__invalid_option__"
        return "invalid-test-value"
    if re.search(r"email|e-mail", lowered):
        return "qa.user@example.test"
    if re.search(r"url|website|web address", lowered):
        return "https://example.test/"
    if re.search(r"password", lowered):
        return "ValidQaPass!234"
    if re.search(r"phone|telephone", lowered):
        return "2025550147"
    if re.search(r"date", lowered):
        return "2027-01-15"
    if re.search(r"price|amount|currency", lowered):
        return "19.99"
    if re.search(r"quantity|count|age|number|numeric", lowered):
        return "3"
    if re.search(r"select|dropdown|option|status", lowered):
        return "Active"
    if re.search(r"project|title|name|user", lowered):
        return "Automation Sample Project"
    return "Sample valid value"


def _limit_story_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not cases:
        return []
    negative_pattern = re.compile(r"negative|validation|invalid|missing|required|reject|blocked|error|must not|not allowed|denied|unsuccessful", re.I)
    positive_pattern = re.compile(r"positive|valid|success|successful|accepts|allows", re.I)
    positive = None
    negative = None
    for case in cases:
        explicit_label = " ".join(str(case.get(key, "")) for key in ("test_type", "title"))
        details = " ".join([
            str(case.get("test_data", "")),
            " ".join(str(item) for item in case.get("expected_results", [])),
            " ".join(str(step.get(key, "")) for step in case.get("steps", []) for key in ("action", "expected_result")),
        ])
        is_negative = bool(negative_pattern.search(explicit_label)) or (not positive_pattern.search(explicit_label) and bool(negative_pattern.search(details)))
        if is_negative and negative is None:
            negative = case
        elif not is_negative and positive is None:
            positive = case
    if positive is None and negative is None:
        positive = cases[0]
    return ([positive] if positive else []) + ([negative] if negative else [])


def _case_tests_authentication(case: dict[str, Any]) -> bool:
    context = " ".join([
        str(case.get("title", "")),
        *(str(step.get("action", "")) + " " + str(step.get("locator_requirement", "")) for step in case.get("steps", [])),
    ])
    return bool(re.search(r"login|log\s*in|sign\s*in|credential|authentication|username.{0,40}password|account.{0,40}(?:identifier|secret)|identifier.{0,40}secret", context, re.I))


def _match_case_locator(action: str, locator_requirement: str, locators: list[dict[str, Any]]) -> dict[str, Any] | None:
    stop_words = {"the", "a", "an", "to", "be", "able", "should", "user", "verify", "verification", "acceptance", "criterion", "criteria", "identify", "relevant", "control", "target", "application", "on", "this", "for", "with", "enter", "fill", "type", "input", "field", "element"}
    aliases = {"username": {"username", "user", "userid", "email", "identifier"}, "identifier": {"username", "user", "userid", "email"}, "password": {"password", "passcode", "secret"}, "secret": {"password", "passcode"}, "login": {"login", "log", "in", "signin", "sign", "authenticate", "submit"}, "submit": {"submit", "login", "signin", "sign", "authenticate"}}
    requested = set(re.findall(r"[a-z0-9]+", f"{action} {locator_requirement}".lower())) - stop_words
    expanded = set(requested)
    for term in requested:
        expanded.update(aliases.get(term, ()))
    best: tuple[int, int, dict[str, Any]] | None = None
    for item in locators:
        if not item.get("validated") and not any(candidate.get("valid") for candidate in item.get("candidates", [])):
            continue
        label_terms = set(re.findall(r"[a-z0-9]+", f"{item.get('element', '')} {item.get('tag', '')}".lower()))
        score = 3 * len(requested & label_terms) + 2 * len((expanded - requested) & label_terms)
        candidate = (score, -len(label_terms), item)
        if score and (best is None or candidate[:2] > best[:2]):
            best = candidate
    return best[2] if best else None
