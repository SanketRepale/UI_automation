# Locator Discovery Skill

## Purpose
Inspect a real target page with Playwright and produce XPath-first locator candidates with observed uniqueness/visibility evidence.

## Inputs
Target URL, selected browser, and live DOM.

## Outputs
For each visible interactive element: element label, unique XPath, alternative role/test-id/ID/label/placeholder/text/CSS candidates, match counts, validation state, confidence, page URL, and rationale.

## Instructions
Navigate to the supplied page; inspect visible controls; derive XPath from the element's actual DOM attributes and visible text rather than assuming its accessible label equals its text; validate that the XPath identifies the exact inspected node and exactly one visible element. Retain that XPath as candidate one and list only uniquely validated alternative locator candidates after it. When semantic XPath matches duplicate controls, try a stable ancestor anchor; use a positional XPath only as a last resort and record that fact in its rationale. The generated script and executor must try XPath first, then validated alternatives in order if the primary no longer resolves uniquely and visibly.

## Constraints
Never claim a locator is valid without evaluating it. Avoid absolute positional paths and unstable IDs. Discovery covers the loaded page only; it does not infer unseen states or authenticated flows.

## Decision Logic
A candidate is validated only when it resolves to exactly one visible element. A primary XPath must also resolve to the exact DOM node inspected. Non-unique candidates remain available for review but are not executable; unique secondary locators may still be used as fallback candidates.

## Failure Handling
Surface navigation, browser-installation, and selector errors with the target URL. Do not fabricate DOM elements.

## Expected Format
JSON records with all candidate counts and explicit validation evidence.
