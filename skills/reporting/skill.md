# Reporting Skill

## Purpose
Summarize persisted execution history without changing underlying results.

## Inputs
Execution runs, test results, step results, and evidence metadata.

## Outputs
Counts by status, pass/fail percentages, duration, trends, and filterable result records.

## Instructions
Count only persisted execution outcomes. Keep BLOCKED and SKIPPED distinct from FAIL. Preserve run, requirement, priority, browser, and evidence traceability.

## Constraints
Never infer PASS from script availability or missing error text. Do not aggregate generated cases as executed outcomes.

## Decision Logic
Pass percentage is passed divided by executed cases (PASS + FAIL); report zero when there are no executed cases. Include blocked/skipped in total run counts.

## Failure Handling
Show an empty state when no execution runs exist.

## Expected Format
Structured summary and records suitable for a Streamlit dashboard and export.
