# Evidence Capture Skill

## Purpose
Capture screenshots tied to the exact test case and step for both passing and failing actions.

## Inputs
Playwright page, run ID, test-case ID, step number, and status.

## Outputs
Stable evidence file path stored on the step result.

## Instructions
Capture after successful steps and immediately after failures when configured. Include the full page when feasible. Keep per-run, per-case, per-step paths.

## Constraints
A screenshot is evidence of rendered state only; it does not establish that an assertion passed. Do not discard browser error details when a screenshot itself fails.

## Decision Logic
Use `step-NN-pass.png` or `step-NN-fail.png` names and associate each path with its persisted step result.

## Failure Handling
Continue result recording if screenshot capture fails; preserve the screenshot exception in logs where available.

## Expected Format
Filesystem path plus status and step metadata.
