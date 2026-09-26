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
        return bool(self.model and self.api_key)

    def complete_json(self, *, system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
        if not self.configured:
            raise LLMError("LLM is not configured. Set LLM_MODEL and LLM_API_KEY, or use the clearly labeled offline draft mode.")
        if self.provider == "anthropic":
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
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as error:
            raise LLMError(f"LLM request failed: {error}") from error
