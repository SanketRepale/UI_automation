# Test Execution Skill

## Purpose
Execute one or more approved cases in Playwright and record independently traceable test- and step-level results.

## Inputs
Approved cases, target URL, browser settings, and validated locators.

## Outputs
Run, test result, and step result records with status, timestamps, duration, URL/title, locator, error, and evidence paths.

## Instructions
Execute each case independently. Continue to the next case after a failure. A missing validated locator or unsupported action is BLOCKED; a performed action or assertion that fails is FAIL. Capture failure context immediately.

## Constraints
Never mark generated-only or unexecuted work as PASS. Do not run Draft or Rejected cases. Do not stop a batch after one case fails by default.

## Decision Logic
PASS requires every mandatory step to execute and pass. A pre-execution blocker yields BLOCKED. Any executed failing step yields FAIL.

## Failure Handling
Record exceptions and current URL/title. Continue with the next case where possible.

## Expected Format
Persisted run, test, and step results with an unambiguous status vocabulary.
