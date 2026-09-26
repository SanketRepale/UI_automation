from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    pass


@dataclass
class LLMProvider:
    provider: str
    base_url: str
    model: str
    api_key: str

    @property
    def configured(self) -> bool:
        if self.provider in {"gemini", "google"}:
            return bool(self.api_key)
        return bool(self.model and self.api_key)

    def complete_json(self, *, system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
        if not self.configured:
            raise LLMError("LLM is not configured. Set LLM_MODEL and LLM_API_KEY, or use the clearly labeled offline draft mode.")
        if self.provider in {"gemini", "google"}:
            preferred = (self.model or "gemini-3.7-flash").strip()
            if preferred.startswith("models/"):
                preferred = preferred[7:]
            models_to_try = [preferred]
            for fallback in ("gemini-3.7-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
                if fallback not in models_to_try:
                    models_to_try.append(fallback)

            base = self.base_url.rstrip("/") if self.base_url and "generativelanguage.googleapis.com" in self.base_url else "https://generativelanguage.googleapis.com/v1beta"
            headers = {
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            }

            last_error: Exception | None = None
            for model_name in models_to_try:
                endpoint = f"{base}/models/{model_name}:generateContent?key={self.api_key}"
                payload = {
                    "system_instruction": {
                        "parts": [{"text": f"{system}\nReturn strictly a valid JSON object matching the requested schema."}]
                    },
                    "contents": [
                        {"role": "user", "parts": [{"text": user}]}
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": temperature,
                    },
                }
                request = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=90) as response:
                        result = json.loads(response.read().decode("utf-8"))
                    candidates = result.get("candidates", [])
                    if not candidates:
                        raise LLMError(f"Gemini ({model_name}) returned empty candidates")
                    parts = candidates[0].get("content", {}).get("parts", [])
                    content = "".join(part.get("text", "") for part in parts).strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    elif content.startswith("```"):
                        content = content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    return json.loads(content.strip())
                except urllib.error.HTTPError as error:
                    try:
                        body = error.read().decode("utf-8", errors="replace")
                        detail = json.loads(body)
                        msg = detail.get("error", {}).get("message") or body
                    except Exception:
                        msg = str(error)

                    # If model not found (404), continue to next latest model
                    if error.code == 404:
                        last_error = LLMError(f"Gemini model {model_name} not found ({msg}); trying fallback")
                        continue

                    # If system_instruction was rejected on Gemini, retry once with embedded prompt
                    if "system_instruction" in str(msg).lower():
                        try:
                            fb_payload = {
                                "contents": [
                                    {"role": "user", "parts": [{"text": f"SYSTEM INSTRUCTIONS:\n{system}\n\nUSER REQUEST:\n{user}\n\nReturn strictly valid JSON only."}]}
                                ],
                                "generationConfig": {
                                    "responseMimeType": "application/json",
                                    "temperature": temperature,
                                },
                            }
                            fb_req = urllib.request.Request(
                                endpoint,
                                data=json.dumps(fb_payload).encode("utf-8"),
                                headers=headers,
                                method="POST",
                            )
                            with urllib.request.urlopen(fb_req, timeout=90) as fb_resp:
                                fb_result = json.loads(fb_resp.read().decode("utf-8"))
                                parts = fb_result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                                fb_content = "".join(part.get("text", "") for part in parts).strip()
                                if fb_content.startswith("```json"):
                                    fb_content = fb_content[7:]
                                elif fb_content.startswith("```"):
                                    fb_content = fb_content[3:]
                                if fb_content.endswith("```"):
                                    fb_content = fb_content[:-3]
                                return json.loads(fb_content.strip())
                        except Exception as fb_err:
                            msg = f"{msg} (fallback prompt failed: {fb_err})"

                    raise LLMError(f"Gemini API error ({error.code}): {msg}") from error
                except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as error:
                    last_error = LLMError(f"Gemini request failed ({model_name}): {error}")
                    continue

            if last_error:
                raise last_error
            raise LLMError("Gemini call failed with all candidate models")

        elif self.provider == "anthropic":
            payload = {
                "model": self.model,
                "max_tokens": 4096,
                "temperature": temperature,
                "system": f"{system}\nReturn only a valid JSON object, without markdown fences.",
                "messages": [{"role": "user", "content": user}],
            }
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            endpoint = f"{self.base_url.rstrip('/')}/messages"
        elif self.provider in {"openai_compatible", "openai"}:
            payload = {
                "model": self.model,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        else:
            raise LLMError(f"Unsupported provider adapter: {self.provider}")

        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
            if self.provider == "anthropic":
                content = "".join(block.get("text", "") for block in result["content"] if block.get("type") == "text")
            else:
                content = result["choices"][0]["message"]["content"]
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            return json.loads(content.strip())
        except urllib.error.HTTPError as error:
            try:
                body = error.read().decode("utf-8", errors="replace")
                detail = json.loads(body)
                msg = detail.get("error", {}).get("message") or body
            except Exception:
                msg = str(error)
            raise LLMError(f"LLM API error ({error.code}): {msg}") from error
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as error:
            raise LLMError(f"LLM request failed: {error}") from error
