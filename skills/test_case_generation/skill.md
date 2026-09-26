# Test Case Generation Skill

## Purpose
Generate reviewable, requirement-traceable test cases with positive and negative coverage where justified.

## Inputs
Requirement analysis JSON and requirement ID.

## Outputs
JSON object containing `test_cases`; each case has `id`, `requirement_id`, `title`, `test_type`, `priority`, `preconditions`, `test_data`, `steps`, `expected_results`, and `postconditions`. Each step has `number`, `action`, `test_data`, `expected_result`, `locator_requirement`, `automation_status`, and an `assertion` object. Executable assertion types are `text_visible`, `text_absent`, `validation_visible`, `element_visible`, `element_value`, `url_contains`, `title_contains`, `checked`, and `not_visible`; assertion objects contain `type` and `value` where needed.

## Instructions
Generate at most two cases for each user story: one positive case and, only when supported by source requirements, one negative/validation case. Cover acceptance criteria across the case steps. Create safe synthetic test data for every data-entry step based on the field, action, constraints, and scenario: realistic valid values for positive cases and representative invalid or missing values for negative cases. Never ask the user to supply test data or leave an executable data-entry step blank. Preserve explicit values and avoid using real credentials or personal data.

Use executable action verbs and a concrete `locator_requirement` for every control interaction. For login stories, split username and password entry into separate steps, click the login control, and verify the resulting page or validation feedback. Do not put negative acceptance criteria into the positive case.

## Constraints
Never invent a UI element or claim an automation-ready locator. New cases start in Draft. Preserve explicit requirement traceability.

## Decision Logic
Map every case to one requirement ID. Split distinct behavior into separate cases. Prefer focused cases with independently verifiable results.

## Failure Handling
Return structured provider errors. If generation is heuristic/offline, label drafts as such and require user review.

## Expected Format
JSON only, with `test_cases` as an array of structured cases.
