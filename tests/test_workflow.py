from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

from ui_automation.agents import PlaywrightScriptAgent, RequirementAgent, TestCaseAgent as CaseGeneratorAgent
from ui_automation.database import Database
from ui_automation.documents import extract_application_details, extract_text, redact_credentials
from ui_automation.executor import ExecutionService
from ui_automation.llm import LLMProvider
from ui_automation.locator_service import LocatorService
from ui_automation.repository import Repository
from ui_automation.utils import JsonLineFormatter, TerminalEventFilter, TerminalEventFormatter, log_event

ROOT = Path(__file__).resolve().parents[1]


def offline_llm() -> LLMProvider:
    return LLMProvider("openai_compatible", "http://localhost/v1", "", "")


def test_offline_analysis_and_generation_are_explicit_drafts() -> None:
    document = """User Story:
As a manager, I want to create a project.

Acceptance Criteria:
1. Project name is mandatory.
2. Valid projects are saved.

Web Application URL: https://qa.example.test/projects
Authentication: Username & Password
Username: qa.person
Password: not-a-real-password
Environment: QA
Browser: chromium
Execution mode: headless
"""
    analysis, application, mode = RequirementAgent(ROOT / "skills", offline_llm()).analyze_documents([("requirements.txt", document)])
    cases, generation_mode = CaseGeneratorAgent(ROOT / "skills", offline_llm()).generate("REQ-1", analysis)
    assert mode.startswith("Offline")
    assert generation_mode.startswith("Offline")
    assert len(cases) <= 2
    assert len(cases) == 2
    assert [case["test_type"] for case in cases] == ["Functional / Positive", "Validation / Negative"]
    assert all(case["status"] == "Draft" for case in cases)
    assert all(case["requirement_id"] == "REQ-1" for case in cases)
    positive_data = [step["test_data"] for step in cases[0]["steps"] if step.get("test_data")]
    assert "Automation Sample Project" in positive_data
    assert "step_1" in cases[1]["test_data"]
    assert cases[1]["test_data"]["step_1"] == ""
    assert analysis["acceptance_criteria"] == ["Project name is mandatory.", "Valid projects are saved."]
    assert application["application_url"] == "https://qa.example.test/projects"
    assert application["username"] == "qa.person"
    assert application["password"] == "not-a-real-password"
    assert "not-a-real-password" not in redact_credentials(document)
    assert "qa.person" not in redact_credentials(document)


def test_offline_login_story_generates_executable_positive_and_negative_flows() -> None:
    criteria = [
        "A member should be able to enter an account identifier and passphrase.",
        "A member should be able to click the Continue button.",
        "Valid credentials should redirect the member to the Operations workspace.",
        "Invalid credentials should display an error message.",
        "A missing account identifier or passphrase should display a validation message.",
        "Suspended accounts should be denied access.",
    ]
    cases, _ = CaseGeneratorAgent(ROOT / "skills", offline_llm()).generate("REQ-LOGIN", {"acceptance_criteria": criteria})

    positive, negative = cases
    assert [step["action"] for step in positive["steps"]] == [
        "Enter account identifier", "Enter account secret", "Click Continue button", "Verify Operations is displayed",
    ]
    assert positive["steps"][2]["assertion"] == {"type": "text_visible", "value": "Operations", "exact": False}
    assert all("invalid credentials" not in expected.lower() for expected in positive["expected_results"])
    assert any(step["action"] == "Enter invalid account identifier" for step in negative["steps"])
    assert any(step["action"] == "Fill Account identifier field with an empty value" for step in negative["steps"])
    assert any(step["action"] == "Enter disabled-account identifier" for step in negative["steps"])
    assert all(step.get("locator_requirement") for step in positive["steps"] if not step.get("assertion"))


def test_configured_generation_keeps_one_positive_and_one_negative_case() -> None:
    class CapturingProvider:
        configured = True

        def complete_json(self, *, system: str, user: str) -> dict[str, object]:
            return {"test_cases": [
                {"title": "Valid project is saved", "test_type": "Positive"},
                {"title": "Missing name is rejected", "test_type": "Negative"},
                {"title": "Second positive", "test_type": "Positive"},
                {"title": "Second negative", "test_type": "Negative"},
            ]}

    cases, _ = CaseGeneratorAgent(ROOT / "skills", CapturingProvider()).generate("REQ-1", {"acceptance_criteria": []})
    assert [case["title"] for case in cases] == ["Valid project is saved", "Missing name is rejected"]


def test_generation_creates_step_data_from_positive_and_negative_email_steps() -> None:
    class CapturingProvider:
        configured = True

        def complete_json(self, *, system: str, user: str) -> dict[str, object]:
            return {"test_cases": [
                {"title": "Valid email accepted", "test_type": "Positive", "steps": [{"action": "Enter a valid email address", "locator_requirement": "Email address input"}]},
                {"title": "Invalid email rejected", "test_type": "Negative", "steps": [{"action": "Enter an invalid email address", "locator_requirement": "Email address input"}]},
            ]}

    cases, _ = CaseGeneratorAgent(ROOT / "skills", CapturingProvider()).generate("REQ-EMAIL", {"acceptance_criteria": []})
    assert cases[0]["steps"][0]["test_data"] == "qa.user@example.test"
    assert cases[1]["steps"][0]["test_data"] == "invalid-email"


def test_configured_llm_never_receives_document_credentials() -> None:
    class CapturingProvider:
        configured = True

        def __init__(self) -> None:
            self.prompt = ""

        def complete_json(self, *, system: str, user: str) -> dict[str, object]:
            self.prompt = user
            return {"user_story": "As a user, I sign in.", "acceptance_criteria": ["Sign-in works."], "scenarios": {}}

    provider = CapturingProvider()
    document = """User Story:
As a user, I want to sign in.
Acceptance Criteria:
1. Sign-in works.
Web Application URL: https://qa.example.test/
Authentication: Username & Password
Username: private.user
Password: SuperSecret-123
"""
    analysis, application, mode = RequirementAgent(ROOT / "skills", provider).analyze_documents([("requirements.md", document)])
    assert mode.startswith("LLM-assisted")
    assert "private.user" not in provider.prompt
    assert "SuperSecret-123" not in provider.prompt
    assert application["username"] == "private.user"
    assert application["password"] == "SuperSecret-123"
    assert "password" not in analysis


def test_url_credentials_are_extracted_locally_and_sanitized() -> None:
    details = extract_application_details("Target: https://doc-user:doc-pass@example.test/app?access_token=private-token")
    assert details["username"] == "doc-user"
    assert details["password"] == "doc-pass"
    assert details["application_url"] == "https://example.test/app?access_token=%5BREDACTED%5D"
    assert "doc-pass" not in redact_credentials("Target: https://doc-user:doc-pass@example.test/app")


def test_tabular_credentials_are_locally_extracted_and_redacted() -> None:
    document = "| Username | Password |\n| --- | --- |\n| sheet-user | sheet-secret |"
    details = extract_application_details(document)
    sanitized = redact_credentials(document)
    assert details["username"] == "sheet-user"
    assert details["password"] == "sheet-secret"
    assert "sheet-user" not in sanitized
    assert "sheet-secret" not in sanitized


def test_sqlite_round_trip_preserves_requirement_and_case(tmp_path: Path) -> None:
    repository = Repository(Database(tmp_path / "test.db"))
    analysis = {"acceptance_criteria": ["Form can be saved"]}
    repository.save_requirement("REQ-1", "Project form", "Create a project", analysis["acceptance_criteria"], analysis, ["spec.txt"])
    case = {"id": "TC-1", "requirement_id": "REQ-1", "title": "Save project", "test_type": "Functional", "priority": "High", "status": "Draft", "steps": []}
    repository.save_test_case(case)
    repository.save_locator({"requirement_id": "REQ-1", "test_case_id": "TC-1", "page_url": "https://app.test", "element": "Case-only button", "candidates": [], "validated": False})
    suite_id = repository.create_suite("Project suite", "Regression cases")
    repository.set_suite_cases(suite_id, ["TC-1"])
    assert repository.suites()[0]["case_count"] == 1
    assert repository.suite_case_ids(suite_id) == ["TC-1"]
    repository.save_application_config({"name": "QA · app.test", "application_url": "https://app.test", "authentication_type": "Username & Password", "environment": "QA", "browser": "chromium", "headless": True, "username_label": "Email", "password_label": "Password", "submit_label": "Sign in", "username": "must-not-store", "password": "must-not-store"})
    stored_profile = repository.application_configs()[0]
    assert stored_profile["name"] == "QA · app.test"
    assert "username" not in stored_profile and "password" not in stored_profile
    with repository.db.connect() as connection:
        profile_columns = {row["name"] for row in connection.execute("PRAGMA table_info(application_configs)")}
    assert "username" not in profile_columns and "password" not in profile_columns
    assert repository.requirements()[0]["analysis"] == analysis
    assert repository.test_cases()[0] == case
    repository.create_run("RUN-1", "http://localhost", "chromium")
    repository.save_result("RUN-1", "TC-1", "BLOCKED", 0.2, "No locator", {}, [{"step_number": 1, "action": "Click save", "status": "BLOCKED", "before_screenshot_path": "before.png", "screenshot_path": "after.png"}])
    saved_step = repository.step_results(repository.results("RUN-1")[0]["id"])[0]
    assert saved_step["before_screenshot_path"] == "before.png"
    assert saved_step["screenshot_path"] == "after.png"
    repository.delete_test_case("TC-1")
    assert repository.test_cases() == []
    assert repository.locators() == []


def test_delete_requirement_cascades_cases_and_requirement_locators(tmp_path: Path) -> None:
    repository = Repository(Database(tmp_path / "delete-requirement.db"))
    repository.save_requirement("REQ-DELETE", "Delete me", "Story", [], {}, [])
    repository.save_test_case({"id": "TC-DELETE", "requirement_id": "REQ-DELETE", "title": "Case", "steps": []})
    repository.save_requirement_target({"requirement_id": "REQ-DELETE", "application_url": "https://app.test"})
    repository.save_locator({"requirement_id": "REQ-DELETE", "test_case_id": "TC-DELETE", "page_url": "https://app.test", "element": "Save", "candidates": [], "validated": False})

    repository.delete_requirement("REQ-DELETE")

    assert repository.requirements() == []
    assert repository.requirement_target("REQ-DELETE") is None
    assert repository.test_cases() == []
    assert repository.locators() == []


def test_requirement_target_and_shared_locators_are_scoped_without_credentials(tmp_path: Path) -> None:
    repository = Repository(Database(tmp_path / "requirement-target.db"))
    repository.save_requirement("REQ-A", "Story A", "A", [], {}, [])
    repository.save_requirement("REQ-B", "Story B", "B", [], {}, [])
    repository.save_test_case({"id": "TC-A", "requirement_id": "REQ-A", "title": "Case A", "steps": []})
    repository.save_test_case({"id": "TC-B", "requirement_id": "REQ-B", "title": "Case B", "steps": []})
    repository.save_requirement_target({"requirement_id": "REQ-A", "application_url": "https://app.test", "guidance": "Project save form", "username": "must-not-be-stored", "password": "must-not-be-stored"})
    shared_locator = {"requirement_id": "REQ-A", "test_case_id": None, "page_url": "https://app.test", "element": "Save project", "candidates": [{"kind": "xpath", "value": "//button", "valid": True}], "validated": True}
    repository.save_locator(shared_locator)
    repository.save_locator(shared_locator)

    assert repository.requirement_target("REQ-A")["guidance"] == "Project save form"
    assert "username" not in repository.requirement_target("REQ-A")
    assert len(repository.locators(requirement_id="REQ-A")) == 1
    assert [item["element"] for item in repository.locators("TC-A", "REQ-A")] == ["Save project"]
    assert repository.locators("TC-B", "REQ-B") == []


def test_text_document_extraction() -> None:
    assert extract_text("story.txt", b"As a tester, I want clear results.") == "As a tester, I want clear results."


def test_generated_script_executes_mapped_click_and_fails_closed_without_assertion() -> None:
    agent = PlaywrightScriptAgent(ROOT / "skills", offline_llm())
    case = {"id": "TC-2", "target_url": "https://example.test", "steps": [{"number": 1, "action": "Click Save button", "test_data": ""}]}
    locators = [{"element": "Save", "xpath": "//button[normalize-space()='Save']", "validated": True}]
    source = agent.generate(case, locators)
    ast.parse(source)
    assert ".click()" in source
    assert "NotImplementedError('Add an explicit executable assertion" in source


def test_script_locator_candidates_keep_xpath_first_and_valid_alternatives() -> None:
    candidates = PlaywrightScriptAgent._script_locator_candidates({
        "xpath": "//button[@aria-label='Save']",
        "validated": True,
        "candidates": [
            {"kind": "xpath", "value": "//button[@aria-label='Save']", "valid": True},
            {"kind": "xpath_absolute", "value": "/html[1]/body[1]/button[1]", "valid": True},
            {"kind": "role", "value": "button: Save", "valid": True},
            {"kind": "text", "value": "Save", "valid": False},
        ],
    })
    assert candidates == [
        {"kind": "xpath", "value": "//button[@aria-label='Save']"},
        {"kind": "xpath_absolute", "value": "/html[1]/body[1]/button[1]"},
        {"kind": "role", "value": "button: Save"},
    ]


def test_script_includes_secondary_locator_resolver() -> None:
    agent = PlaywrightScriptAgent(ROOT / "skills", offline_llm())
    case = {"id": "TC-FALLBACK", "target_url": "https://example.test", "steps": [{"number": 1, "action": "Click Save button", "test_data": "", "assertion": {"type": "text_visible", "value": "Saved"}}]}
    locators = [{"element": "Save", "xpath": "//button[@aria-label='Save']", "validated": True, "candidates": [{"kind": "xpath", "value": "//button[@aria-label='Save']", "valid": True}, {"kind": "role", "value": "button: Save", "valid": True}]}]
    source = agent.generate(case, locators)
    ast.parse(source)
    assert "def resolve_locator(page, candidates):" in source
    assert "kind in ('xpath', 'xpath_absolute')" in source
    assert '"kind": "role", "value": "button: Save"' in source


def test_absolute_xpath_helper_is_available_on_locator_service() -> None:
    class FakeTarget:
        def evaluate(self, expression: str) -> str:
            return "/html[1]/body[1]/button[1]"

    assert LocatorService._absolute_xpath(FakeTarget()) == "/html[1]/body[1]/button[1]"


def test_locator_guidance_matches_element_text_and_attributes() -> None:
    matches = LocatorService._guidance_matches(
        "Find the cart action",
        {"text": "Add to Cart", "id": "cart_button", "tag": "button"},
    )
    assert matches == ["cart"]


def test_locator_login_infers_controls_when_labels_are_omitted() -> None:
    class FakeControl:
        def __init__(self) -> None:
            self.value = ""
            self.clicked = False

        def count(self) -> int:
            return 1

        def nth(self, index: int) -> "FakeControl":
            return self

        def is_visible(self) -> bool:
            return True

        def fill(self, value: str) -> None:
            self.value = value

        def click(self) -> None:
            self.clicked = True

        def wait_for(self, *, state: str) -> None:
            assert state == "visible"

    class FakePage:
        def __init__(self) -> None:
            self.username = FakeControl()
            self.password = FakeControl()
            self.submit = FakeControl()

        def locator(self, selector: str) -> FakeControl:
            if selector == "input[type='password']":
                return self.password
            if selector == "body":
                return FakeControl()
            return self.username

        def get_by_role(self, role: str, *, name: object) -> FakeControl:
            assert role == "button"
            return self.submit

    page = FakePage()
    LocatorService._authenticate(page, {"username": "qa-user", "password": "qa-password"})

    assert page.username.value == "qa-user"
    assert page.password.value == "qa-password"
    assert page.submit.clicked


def test_click_action_label_containing_check_is_not_a_checkbox_action() -> None:
    class FakeLocator:
        clicked = False

        def click(self) -> None:
            self.clicked = True

    locator = FakeLocator()
    ExecutionService._perform_action(None, locator, "Click Run check button", "")
    assert locator.clicked


def test_execution_matches_locator_requirements_to_shared_element_labels() -> None:
    locators = [
        {"element": "Account identifier", "tag": "input", "validated": True, "candidates": [{"kind": "xpath", "value": "//input[@name='account']", "valid": True}]},
        {"element": "Account secret", "tag": "input", "validated": True, "candidates": [{"kind": "xpath", "value": "//input[@name='secret']", "valid": True}]},
        {"element": "Continue", "tag": "button", "validated": True, "candidates": [{"kind": "role", "value": "button: Continue", "valid": True}]},
        {"element": "Operations", "tag": "h1", "validated": True, "candidates": [{"kind": "text", "value": "Operations", "valid": True}]},
    ]
    assert ExecutionService._match_locator("Enter account identifier", locators, "Account identifier field")["element"] == "Account identifier"
    assert ExecutionService._match_locator("Enter account secret", locators, "Account secret field")["element"] == "Account secret"
    assert ExecutionService._match_locator("Click Continue button", locators, "Continue button")["element"] == "Continue"
    assert ExecutionService._match_locator("Verify Operations is displayed", locators, "Operations page or heading")["element"] == "Operations"


def test_login_case_skips_automatic_authentication_and_resolves_credentials() -> None:
    case = {"title": "Verify positive acceptance criteria", "steps": [
        {"action": "Enter account identifier", "locator_requirement": "Account identifier field"},
        {"action": "Enter account secret", "locator_requirement": "Account secret field"},
        {"action": "Submit sign-in form", "locator_requirement": "Sign-in submit control"},
    ]}
    assert ExecutionService._tests_authentication_flow(case)
    assert ExecutionService._runtime_test_data("{{username}}", {"username": "demo", "password": "secret"}) == "demo"
    assert ExecutionService._runtime_test_data("{{password}}", {"username": "demo", "password": "secret"}) == "secret"


def test_structured_log_event_contains_trace_context() -> None:
    logger = logging.getLogger("test.structured-events")
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLineFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        record = logger.makeRecord(logger.name, logging.INFO, __file__, 1, "step_completed", (), None, extra={"event_data": {"agent": "ExecutionAgent", "action": "step_completed", "run_id": "RUN-1", "test_case_id": "TC-1", "step_number": 2, "status": "PASS"}})
        event = json.loads(handler.format(record))
        assert event["agent"] == "ExecutionAgent"
        assert event["run_id"] == "RUN-1"
        assert event["test_case_id"] == "TC-1"
        assert event["step_number"] == 2
        assert event["status"] == "PASS"
        assert event["timestamp"]
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_terminal_logs_keep_failures_and_hide_routine_step_noise() -> None:
    logger = logging.getLogger("test.terminal-events")
    record = logger.makeRecord(logger.name, logging.INFO, __file__, 1, "step_completed", (), None, extra={"event_data": {"agent": "ExecutionAgent", "action": "step_completed", "status": "PASS"}})
    assert not TerminalEventFilter().filter(record)
    failure = logger.makeRecord(logger.name, logging.ERROR, __file__, 1, "locator_discovery_failed", (), None, extra={"event_data": {"agent": "LocatorAgent", "action": "locator_discovery_failed", "error": "browser launch failed"}})
    assert TerminalEventFilter().filter(failure)
    assert TerminalEventFormatter().format(failure) == "ERROR [LocatorAgent] locator discovery failed | error=browser launch failed"


def test_authenticated_script_uses_environment_secrets_not_literals() -> None:
    agent = PlaywrightScriptAgent(ROOT / "skills", offline_llm())
    case = {"id": "TC-3", "target_url": "https://app.test", "authentication_type": "Username & Password", "username_label": "Email", "password_label": "Password", "submit_label": "Sign in", "steps": []}
    source = agent.generate(case, [])
    ast.parse(source)
    assert "UI_AUTOMATION_USERNAME" in source and "UI_AUTOMATION_PASSWORD" in source
    assert 'page.get_by_label("Email"' in source
    assert "private.user" not in source and "SuperSecret-123" not in source


def test_authenticated_script_infers_controls_without_optional_labels() -> None:
    agent = PlaywrightScriptAgent(ROOT / "skills", offline_llm())
    case = {"id": "TC-LOGIN-INFER", "target_url": "https://app.test", "authentication_type": "Username & Password", "steps": []}
    source = agent.generate(case, [])
    ast.parse(source)
    assert "input[autocomplete='username']" in source
    assert "input[type='password']" in source
    assert "log\\s*in|sign\\s*in|submit" in source


def test_login_script_uses_shared_locators_without_auto_login() -> None:
    agent = PlaywrightScriptAgent(ROOT / "skills", offline_llm())
    case = {
        "id": "TC-LOGIN-FLOW",
        "target_url": "https://app.test",
        "authentication_type": "Username & Password",
        "steps": [
            {"number": 1, "action": "Enter account identifier", "locator_requirement": "Account identifier field", "test_data": "{{username}}"},
            {"number": 2, "action": "Enter account secret", "locator_requirement": "Account secret field", "test_data": "{{password}}"},
            {"number": 3, "action": "Click Continue button", "locator_requirement": "Continue button", "test_data": ""},
            {"number": 4, "action": "Verify Operations is displayed", "assertion": {"type": "text_visible", "value": "Operations", "exact": False}},
        ],
    }
    locators = [
        {"element": "Account identifier", "tag": "input", "validated": True, "candidates": [{"kind": "xpath", "value": "//input[@name='account']", "valid": True}]},
        {"element": "Account secret", "tag": "input", "validated": True, "candidates": [{"kind": "xpath", "value": "//input[@name='secret']", "valid": True}]},
        {"element": "Continue", "tag": "button", "validated": True, "candidates": [{"kind": "role", "value": "button: Continue", "valid": True}]},
    ]

    source = agent.generate(case, locators)
    ast.parse(source)

    assert "step_locator_1.fill(username)" in source
    assert "step_locator_2.fill(password)" in source
    assert "username_field.fill(username)" not in source
    assert "expect(page.get_by_text(\"Operations\", exact=False)).to_be_visible()" in source


def test_script_supports_validation_assertions_without_a_saved_message_locator() -> None:
    agent = PlaywrightScriptAgent(ROOT / "skills", offline_llm())
    case = {
        "id": "TC-LOGIN-NEGATIVE",
        "target_url": "https://app.test",
        "authentication_type": "Username & Password",
        "steps": [{
            "number": 1,
            "action": "Verify login validation message",
            "assertion": {"type": "validation_visible"},
        }],
    }

    source = agent.generate(case, [])
    ast.parse(source)

    assert "[role='alert']" in source
    assert "Expected visible validation feedback" in source
