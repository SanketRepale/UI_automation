from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from ui_automation.config import Settings


class LocatorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def discover(self, url: str, browser_name: str | None = None, authentication: dict[str, Any] | None = None, guidance: str = "") -> list[dict[str, Any]]:
        with sync_playwright() as playwright:
            browser_choice = browser_name or self.settings.browser or "chromium"
            browser_type = getattr(playwright, browser_choice)
            browser = browser_type.launch(headless=self.settings.headless)
            page = browser.new_page()
            page.set_default_timeout(self.settings.timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            results = []
            if authentication and authentication.get("authentication_type") == "Username & Password":
                results.extend(self._discover_current_page(page, guidance))
                self._authenticate(page, authentication)
            results.extend(self._discover_current_page(page, guidance))
            browser.close()
            unique_results = {}
            for item in results:
                key = (item["page_url"], item["element"], item["tag"], item["xpath"])
                unique_results[key] = item
            return sorted(unique_results.values(), key=lambda item: len(item["guidance_matches"]), reverse=True)

    def _discover_current_page(self, page: Any, guidance: str) -> list[dict[str, Any]]:
            elements = page.locator("button, input, textarea, select, a, [role], [data-testid]").evaluate_all("""nodes => nodes.map((node, index) => {
              const rect = node.getBoundingClientRect();
              const visible = !!(rect.width || rect.height) && getComputedStyle(node).visibility !== 'hidden';
              const associatedLabel = node.labels ? Array.from(node.labels).map(label => label.innerText).join(' ') : '';
                            const visibleText = String(node.innerText || node.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120);
                            const label = node.getAttribute('aria-label') || associatedLabel || node.getAttribute('placeholder') || visibleText || node.getAttribute('name') || node.getAttribute('title') || '';
                            const ancestors = [];
                            for (let parent = node.parentElement; parent; parent = parent.parentElement) {
                                const id = parent.id || '';
                                const testId = parent.getAttribute('data-testid') || '';
                                const ariaLabel = parent.getAttribute('aria-label') || '';
                                if (id || testId || ariaLabel) ancestors.push({tag: parent.tagName.toLowerCase(), id, test_id: testId, aria_label: ariaLabel});
                            }
                            return {tag: node.tagName.toLowerCase(), text: String(label).trim().replace(/\\s+/g, ' ').slice(0, 120), visible_text: visibleText, id: node.id || '', name: node.getAttribute('name') || '', placeholder: node.getAttribute('placeholder') || '', aria_label: node.getAttribute('aria-label') || '', role: node.getAttribute('role') || '', type: node.getAttribute('type') || '', test_id: node.getAttribute('data-testid') || '', ancestors, visible, index};
            }).filter(item => item.visible && item.text)""")
            results = []
            for element in elements:
                text = element["text"]
                guidance_matches = self._guidance_matches(guidance, element)
                target = page.locator("button, input, textarea, select, a, [role], [data-testid]").nth(int(element["index"]))
                xpath, xpath_count, xpath_reason = self._unique_xpath(page, target, element)
                candidates = [{"kind": "xpath", "value": xpath, "count": xpath_count, "valid": xpath_count == 1, "reason": xpath_reason}]
                absolute_xpath = self._absolute_xpath(target)
                absolute_locator = page.locator(f"xpath={absolute_xpath}")
                absolute_count = absolute_locator.count()
                absolute_valid = absolute_count == 1 and absolute_locator.is_visible() and self._position_in_xpath(target, absolute_xpath) == 1
                candidates.append({"kind": "xpath_absolute", "value": absolute_xpath, "count": absolute_count, "valid": absolute_valid, "reason": "absolute DOM path fallback"})
                if element.get("test_id"):
                    self._append_candidate(page, target, candidates, "test_id", element["test_id"])
                if element.get("id"):
                    self._append_candidate(page, target, candidates, "id", element["id"])
                if element.get("role") or element["tag"] in {"button", "a"}:
                    role = element.get("role") or ("button" if element["tag"] == "button" else "link")
                    self._append_candidate(page, target, candidates, "role", f"{role}: {text}")
                if element.get("placeholder"):
                    self._append_candidate(page, target, candidates, "placeholder", element["placeholder"])
                if element.get("aria_label") or element["tag"] in {"input", "textarea"}:
                    self._append_candidate(page, target, candidates, "label", text)
                if text:
                    self._append_candidate(page, target, candidates, "text", text)
                if element.get("name"):
                    css = f"{element['tag']}[name={self._css_quote(element['name'])}]"
                    self._append_candidate(page, target, candidates, "css", css)
                alternatives = [candidate for candidate in candidates[1:] if candidate["valid"]]
                explanation = f"Primary XPath was validated against the live element. {xpath_reason} {len(alternatives)} unique alternative locator(s) are available as fallbacks."
                if guidance_matches:
                    explanation += " Guidance matched: " + ", ".join(guidance_matches) + "."
                results.append({"element": text, "tag": element["tag"], "xpath": xpath, "candidates": candidates, "selected": xpath, "validated": xpath_count == 1, "confidence": 0.95 if xpath_count == 1 and "positional" not in xpath_reason.lower() else 0.75, "guidance_matches": guidance_matches, "page_url": page.url, "last_validated": datetime.now(timezone.utc).isoformat(), "explanation": explanation})
            return results

    @staticmethod
    def _guidance_matches(guidance: str, element: dict[str, Any]) -> list[str]:
        terms = set(re.findall(r"[a-z0-9]+", guidance.lower()))
        terms = {term for term in terms if len(term) > 2} - {"the", "and", "for", "with", "from", "that", "this", "button", "field", "element"}
        searchable = " ".join(str(element.get(key, "")) for key in ("text", "visible_text", "tag", "id", "name", "placeholder", "aria_label", "role", "test_id")).lower()
        return sorted(term for term in terms if re.search(rf"\b{re.escape(term)}\b", searchable))

    @staticmethod
    def _authenticate(page: Any, authentication: dict[str, Any]) -> None:
        username = authentication.get("username")
        password = authentication.get("password")
        if not username or not password:
            raise ValueError("Provide both username and password to inspect an authenticated page.")

        username_label = authentication.get("username_label", "")
        password_label = authentication.get("password_label", "")
        submit_label = authentication.get("submit_label", "")
        username_candidates = [page.get_by_label(username_label, exact=True)] if username_label else []
        username_candidates.extend([
            page.locator("input[autocomplete='username']"),
            page.locator("input[type='email']"),
            page.locator("form input:not([type='password']):not([type='hidden']):not([type='submit'])"),
            page.locator("input:not([type='password']):not([type='hidden']):not([type='submit'])"),
        ])
        password_candidates = [page.get_by_label(password_label, exact=True)] if password_label else []
        password_candidates.append(page.locator("input[type='password']"))
        submit_candidates = [page.get_by_role("button", name=submit_label, exact=True)] if submit_label else []
        submit_candidates.extend([
            page.get_by_role("button", name=re.compile(r"log\s*in|sign\s*in|submit|continue|next|verify|authenticate", re.I)),
            page.locator("button[type='submit'], input[type='submit'], [role='button'][type='submit']"),
            page.locator("form button:not([type='button'])"),
        ])

        def first_visible(candidates: list[Any]) -> Any | None:
            for candidate in candidates:
                try:
                    for index in range(candidate.count()):
                        match = candidate.nth(index)
                        if match.is_visible():
                            return match
                except PlaywrightError:
                    continue
            return None

        username_field = first_visible(username_candidates)
        password_field = first_visible(password_candidates)
        submit_button = first_visible(submit_candidates)
        if not username_field or not password_field or not submit_button:
            raise ValueError("Could not identify visible sign-in controls. Add their labels in optional login details.")
        username_field.fill(str(username))
        password_field.fill(str(password))
        submit_button.click()
        page.locator("body").wait_for(state="visible")

    def validate(self, url: str, candidate: dict[str, str], browser_name: str | None = None) -> int:
        with sync_playwright() as playwright:
            browser = getattr(playwright, browser_name or self.settings.browser).launch(headless=self.settings.headless)
            page = browser.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded")
                kind, value = candidate["kind"], candidate["value"]
                locator = self._playwright_locator(page, kind, value)
                count = locator.count()
                return count if count == 1 and locator.is_visible() else count
            except PlaywrightError:
                return 0
            finally:
                browser.close()

    @staticmethod
    def _playwright_locator(page: Any, kind: str, value: str) -> Any:
        if kind in {"xpath", "xpath_absolute"}:
            return page.locator(f"xpath={value}")
        if kind == "test_id":
            return page.get_by_test_id(value)
        if kind == "id":
            selector = page.evaluate("id => '#' + CSS.escape(id)", value)
            return page.locator(selector)
        if kind == "placeholder":
            return page.get_by_placeholder(value, exact=True)
        if kind == "label":
            return page.get_by_label(value, exact=True)
        if kind == "text":
            return page.get_by_text(value, exact=True)
        if kind == "css":
            return page.locator(value)
        if kind == "role":
            role, name = value.split(": ", 1)
            return page.get_by_role(role, name=name, exact=True)
        raise ValueError(f"Unsupported locator kind: {kind}")

    @classmethod
    def _append_candidate(cls, page: Any, target: Any, candidates: list[dict[str, Any]], kind: str, value: str) -> None:
        try:
            locator = cls._playwright_locator(page, kind, value)
            count = locator.count()
            valid = count == 1 and locator.is_visible() and locator.evaluate("(node, expected) => node === expected", target.element_handle())
        except (PlaywrightError, ValueError):
            count = 0
            valid = False
        candidates.append({"kind": kind, "value": value, "count": count, "valid": bool(valid)})

    @staticmethod
    def _absolute_xpath(target: Any) -> str:
        return str(target.evaluate("""el => {
          const parts = [];
          for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
            let index = 1;
            for (let sibling = node.previousElementSibling; sibling; sibling = sibling.previousElementSibling) {
              if (sibling.tagName === node.tagName) index++;
            }
            parts.unshift(`${node.tagName.toLowerCase()}[${index}]`);
          }
          return '/' + parts.join('/');
        }"""))

    @staticmethod
    def _input_xpath(element: dict[str, Any]) -> str:
        for attribute in ("name", "placeholder", "aria_label"):
            value = element.get(attribute)
            if value:
                xpath_attribute = "aria-label" if attribute == "aria_label" else attribute
                return f"//{element['tag']}[@{xpath_attribute}={LocatorService._xpath_literal(str(value))}]"
        identifier = str(element.get("id", ""))
        if identifier and not re.search(r"(?:^|[-_])[0-9a-f]{6,}$|\\d{5,}", identifier, re.I):
            return f"//{element['tag']}[@id={LocatorService._xpath_literal(identifier)}]"
        return f"(//{element['tag']})[{int(element['index']) + 1}]"

    def _unique_xpath(self, page: Any, target: Any, element: dict[str, Any]) -> tuple[str, int, str]:
        tag = element["tag"]
        attribute_candidates: list[tuple[str, str]] = []
        for key, attribute in (("test_id", "data-testid"), ("id", "id"), ("name", "name"), ("aria_label", "aria-label"), ("placeholder", "placeholder")):
            value = element.get(key)
            if value and (key != "id" or not re.search(r"(?:^|[-_])[0-9a-f]{6,}$|\d{5,}", str(value), re.I)):
                attribute_candidates.append((f"//{tag}[@{attribute}={self._xpath_literal(str(value))}]", f"matched the element's {attribute} attribute"))
        visible_text = element.get("visible_text", "")
        if visible_text:
            attribute_candidates.append((f"//{tag}[normalize-space(.)={self._xpath_literal(visible_text)}]", "matched normalized visible DOM text"))

        base_attribute_candidates = tuple(attribute_candidates)
        for ancestor in element.get("ancestors", []):
            for key, attribute in (("test_id", "data-testid"), ("id", "id"), ("aria_label", "aria-label")):
                value = ancestor.get(key)
                if not value or (key == "id" and re.search(r"(?:^|[-_])[0-9a-f]{6,}$|\d{5,}", str(value), re.I)):
                    continue
                anchor = f"//*[@{attribute}={self._xpath_literal(str(value))}]"
                for suffix, reason in base_attribute_candidates:
                    predicate = suffix[suffix.index("["):]
                    anchored = f"{anchor}//{tag}{predicate}"
                    attribute_candidates.append((anchored, f"used a stable {attribute} ancestor and {reason}"))

        for xpath, reason in attribute_candidates:
            locator = page.locator(f"xpath={xpath}")
            count = locator.count()
            if count == 1 and self._position_in_xpath(target, xpath) == 1 and locator.is_visible():
                return xpath, count, reason

        for xpath, reason in attribute_candidates:
            locator = page.locator(f"xpath={xpath}")
            count = locator.count()
            if count > 1:
                target_position = self._position_in_xpath(target, xpath)
                if target_position:
                    positional = f"({xpath})[{target_position}]"
                    positional_locator = page.locator(f"xpath={positional}")
                    if positional_locator.count() == 1 and positional_locator.is_visible():
                        return positional, 1, f"used a positional XPath fallback because the semantic XPath matched {count} elements"

        tag_expression = f"//{tag}"
        target_position = self._position_in_xpath(target, tag_expression)
        if target_position:
            positional = f"({tag_expression})[{target_position}]"
            locator = page.locator(f"xpath={positional}")
            if locator.count() == 1 and locator.is_visible():
                return positional, 1, "used a positional XPath relative to matching elements because no stable attribute/text XPath was unique"
        return tag_expression, 0, "unable to build an XPath that uniquely resolves the inspected element"

    @staticmethod
    def _position_in_xpath(target: Any, expression: str) -> int:
        return int(target.evaluate(
            "(el, xpath) => { const result = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null); for (let i = 0; i < result.snapshotLength; i++) if (result.snapshotItem(i) === el) return i + 1; return 0; }",
            expression,
        ))

    @staticmethod
    def _xpath_literal(value: str) -> str:
        if "'" not in value:
            return f"'{value}'"
        if '"' not in value:
            return f'"{value}"'
        parts = value.split("'")
        return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"

    @staticmethod
    def _css_quote(value: str) -> str:
        return '"' + re.sub(r'([\\" ])', r"\\\1", value) + '"'

    @staticmethod
    def _css_escape(value: str) -> str:
        return re.sub(r"([^a-zA-Z0-9_-])", lambda match: "\\" + match.group(1), value)
