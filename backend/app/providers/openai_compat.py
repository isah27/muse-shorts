"""Shared OpenAI-compatible chat client used by both Meta Model API and Baseten.

Reasoning models (Muse Spark Open) return their chain of thought in
`message.reasoning_content` and the final answer in `message.content`. We read them separately:
the answer is parsed from `content`; the reasoning is surfaced (truncated) to the agent event stream.
"""
from __future__ import annotations
import json, re, time
from dataclasses import dataclass
import httpx

def extract_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"model did not return JSON: {text[:200]}")
    return json.loads(text[start:end + 1])

@dataclass
class Completion:
    content: str
    reasoning: str = ""
    finish_reason: str = ""
    usage: dict | None = None

class ChatLLM:
    def __init__(self, name: str, base_url: str, api_key: str, model: str,
                 json_mode: bool, extra: dict | None = None, auth_scheme: str = "Bearer",
                 system_role: str = "developer", max_tokens: int | None = None, timeout: float = 240):
        if not api_key:
            raise RuntimeError(f"{name}: API key missing (see .env.example)")
        self.name, self.base_url, self.api_key, self.model = name, base_url.rstrip("/"), api_key, model
        self.json_mode, self.extra = json_mode, extra or {}
        self.auth_scheme, self.system_role, self.max_tokens, self.timeout = auth_scheme, system_role, max_tokens, timeout

    def chat_full(self, messages: list[dict], **kw) -> Completion:
        body = {"model": self.model, "messages": messages, **self.extra, **kw}
        if self.max_tokens and "max_tokens" not in body:
            body["max_tokens"] = self.max_tokens
        headers = {"Authorization": f"{self.auth_scheme} {self.api_key}"}  # never logged
        last: Exception | None = None
        for attempt in range(4):
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout, headers=headers)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt); continue
                r.raise_for_status()
                ch = r.json()["choices"][0]
                msg = ch["message"]
                return Completion(msg.get("content") or "", msg.get("reasoning_content") or msg.get("reasoning") or "",
                                  ch.get("finish_reason") or "", r.json().get("usage"))
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
                if attempt < 3:
                    time.sleep(2 ** attempt); continue
        raise RuntimeError(f"{self.name}: request failed: {type(last).__name__}")

    def chat(self, messages: list[dict], **kw) -> str:
        return self.chat_full(messages, **kw).content

    def complete_json_ex(self, system: str, user: str, schema_hint: str = "") -> tuple[dict, str]:
        """Returns (parsed JSON from content, reasoning_content). Retries once if the answer was cut off/unparseable."""
        msgs = [{"role": self.system_role, "content": system + ("\n\nReturn ONLY JSON matching:\n" + schema_hint if schema_hint else "")},
                {"role": "user", "content": user}]
        kw = {"response_format": {"type": "json_object"}} if self.json_mode else {}
        err: Exception | None = None
        for _ in range(2):
            c = self.chat_full(msgs, **kw)
            try:
                return extract_json(c.content), c.reasoning
            except (ValueError, json.JSONDecodeError) as e:
                err = e
        raise ValueError(f"{self.name}: no parseable JSON in answer ({err})")

    def complete_json(self, system: str, user: str, schema_hint: str = "") -> dict:
        return self.complete_json_ex(system, user, schema_hint)[0]
