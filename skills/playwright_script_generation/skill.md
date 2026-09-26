# Playwright Script Generation Skill

## Purpose
Generate readable Python Playwright scripts from a reviewed test case and validated locator repository.

## Inputs
Structured test case, target URL, and validated locators.

## Outputs
Standalone Python Playwright test source suitable for inspection and editing.

## Instructions
Use locators that were actually validated, assertions for expected outcomes, explicit waits, and screenshots. Leave visible TODOs for unmapped steps; never silently replace missing locators with guesses.

## Constraints
Script generation is not execution. Do not claim a generated script passes. Keep secrets out of source.

## Decision Logic
Use XPath-first locator values unless the user selected and validated a stronger recorded alternative. Emit an explicit TODO for every step without a matching locator/action mapping.

## Failure Handling
Refuse to label a script ready when steps are unmapped; make review gaps visible.

## Expected Format
Executable-looking Python source with imports, a test function, assertions, and evidence capture; unresolved work must remain explicit.
