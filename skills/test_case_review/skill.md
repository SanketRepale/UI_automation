# Test Case Review Skill

## Purpose
Check the completeness, clarity, feasibility, and traceability of a generated or edited test case.

## Inputs
One structured test case and the source acceptance criteria.

## Outputs
A list of review issues; an empty list means basic structural checks passed, not that the case is approved or executed.

## Instructions
Check required fields, actionable steps, expected results, test data, preconditions, and criterion traceability. Flag assumptions and ambiguous language.

## Constraints
Do not rewrite requirements or approve a case on the user's behalf. Structural validity is not execution evidence.

## Decision Logic
Missing core fields or no steps are blocking review issues. Unclear traceability should be called out for human confirmation.

## Failure Handling
If source criteria are unavailable, report that traceability could not be checked.

## Expected Format
Plain list of concise, actionable review issues.
