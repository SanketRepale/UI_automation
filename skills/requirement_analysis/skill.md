# Requirement Analysis Skill

## Purpose
Analyze uploaded requirement documents and extract a traceable requirement model plus explicitly stated application setup facts.

## Inputs
Text extracted from uploaded PDF, DOCX, XLSX, CSV, TXT, or Markdown files. The application locally extracts username/password values and redacts them before creating an LLM prompt.

## Outputs
JSON object with `requirement_title`, `user_story`, `acceptance_criteria`, `business_rules`, `scenarios`, `test_data_requirements`, `dependencies`, `expected_ui_behavior`, `automation_gaps`, and `ambiguities`. Include `application_url`, `authentication_type`, `environment`, `browser`, and `execution_mode` in `application_details` only when explicitly present in the uploaded files.

## Instructions
Preserve source meaning. Extract the story, acceptance criteria, business rules, positive/negative/boundary scenarios, test data, and automation gaps. Separate observed facts from assumptions and retain ambiguities as questions. Do not silently discard conflicting source statements.

## Constraints
Do not invent product behavior, UI controls, URLs, environments, or authorization rules. Keep source wording when interpretation is uncertain. Never request, reproduce, or infer username/password values; these are removed locally before the prompt is sent.

## Decision Logic
Use explicit criteria as authoritative. Use the full uploaded document text as supporting context. If a story, URL, authentication type, environment, browser, or execution mode is missing, report that it is absent so the UI can request only that information. Do not add placeholder URLs or default authentication assumptions.

## Failure Handling
Report parse/provider errors. Do not claim an LLM analysis when the offline heuristic path was used.

## Expected Format
A JSON object matching the output fields above; arrays contain concise strings.
