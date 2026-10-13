"""DeepSeek client (OpenAI-compatible Chat Completions API).

Every agent call goes through :meth:`LLMClient.chat_json`, which records a call log so the
orchestrator can report which agents made independent model calls and how long they took.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import settings

log = logging.getLogger("mealagent.llm")


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """Raised when no API key is configured (offline mode)."""


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating ```json fences and surrounding prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"model did not return valid JSON: {text[:200]}")


def image_data_url(data: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


@dataclass
class CallRecord:
    agent: str
    model: str
    ok: bool
    seconds: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""


@dataclass
class LLMClient:
    api_key: str = field(default_factory=lambda: settings.deepseek_api_key)
    base_url: str = field(default_factory=lambda: settings.deepseek_base_url)
    model: str = field(default_factory=lambda: settings.deepseek_model)
    vision_model: str = field(default_factory=lambda: settings.vision_model)
    vision_base_url: str = field(default_factory=lambda: settings.vision_base_url or settings.deepseek_base_url)
    vision_api_key: str = field(default_factory=lambda: settings.vision_api_key or settings.deepseek_api_key)
    timeout: float = field(default_factory=lambda: settings.llm_timeout)
    offline: bool = field(default_factory=lambda: not settings.llm_online)
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def online(self) -> bool:
        return not self.offline and bool(self.api_key)

    async def _post(self, base_url: str, api_key: str, payload: dict) -> dict:
        url = base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}"})
        if resp.status_code >= 400:
            raise LLMError(f"DeepSeek API {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def chat(self, messages: list[dict], *, agent: str = "", json_mode: bool = False,
                   temperature: float = 0.3, max_tokens: int = 4096, vision: bool = False) -> str:
        if not self.online:
            raise LLMUnavailable("DEEPSEEK_API_KEY is not configured")
        model = self.vision_model if vision else self.model
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature,
                                   "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        try:
            data = await self._post(self.vision_base_url if vision else self.base_url,
                                    self.vision_api_key if vision else self.api_key, payload)
            content = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage") or {}
            self.calls.append(CallRecord(agent, model, True, time.monotonic() - started,
                                         usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)))
            return content
        except (httpx.HTTPError, KeyError, IndexError, LLMError) as exc:
            self.calls.append(CallRecord(agent, model, False, time.monotonic() - started, error=str(exc)[:200]))
            raise LLMError(str(exc)) from exc

    async def chat_json(self, system: str, user: str | dict, *, agent: str = "",
                        images: list[str] | None = None, temperature: float = 0.3) -> Any:
        """One independent model call that must return a JSON object."""
        user_text = user if isinstance(user, str) else json.dumps(user, ensure_ascii=False)
        if images:
            content: Any = [{"type": "text", "text": user_text}] + [
                {"type": "image_url", "image_url": {"url": url}} for url in images]
        else:
            content = user_text
        messages = [{"role": "system", "content": system + "\n\n只输出一个 JSON 对象，不要输出其他内容。"},
                    {"role": "user", "content": content}]
        text = await self.chat(messages, agent=agent, json_mode=True, temperature=temperature,
                               vision=bool(images))
        return extract_json(text)

    def usage_summary(self) -> dict:
        return {
            "calls": len(self.calls),
            "by_agent": {a: sum(1 for c in self.calls if c.agent == a) for a in dict.fromkeys(c.agent for c in self.calls)},
            "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "completion_tokens": sum(c.completion_tokens for c in self.calls),
            "failures": [c.error for c in self.calls if not c.ok],
        }


def new_client() -> LLMClient:
    """A fresh client per request/job so call logs don't mix."""
    return LLMClient()
