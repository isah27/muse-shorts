import json, httpx
from app.providers.openai_compat import ChatLLM
from app.providers import baseten
from app import config as C

def mk(handler, **kw):
    llm = ChatLLM("t", "https://x/v1", "SECRETKEY", "m", json_mode=False, auth_scheme="Api-Key", system_role="system", max_tokens=9999, **kw)
    real = httpx.post
    httpx.post = lambda url, **k: handler(k)  # type: ignore
    return llm, lambda: setattr(httpx, "post", real)

def resp(content, reasoning="", status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content, "reasoning_content": reasoning}, "finish_reason": "stop"}]},
                          request=httpx.Request("POST", "https://x"))

def test_reads_content_and_reasoning_separately_and_sets_auth_and_max_tokens():
    seen = {}
    def h(k):
        seen.update(k); return resp('{"a": 1}', "I should answer with a=1")
    llm, undo = mk(h)
    try:
        d, reasoning = llm.complete_json_ex("sys", "user")
    finally: undo()
    assert d == {"a": 1} and reasoning == "I should answer with a=1"
    assert seen["headers"]["Authorization"] == "Api-Key SECRETKEY"
    assert seen["json"]["max_tokens"] == 9999 and seen["json"]["messages"][0]["role"] == "system"

def test_json_is_not_taken_from_reasoning_and_retries_when_content_empty():
    calls = []
    def h(k):
        calls.append(1)
        return resp("", '{"fake": true}') if len(calls) == 1 else resp('```json\n{"ok": true}\n```', "")
    llm, undo = mk(h)
    try: d, _ = llm.complete_json_ex("s", "u")
    finally: undo()
    assert d == {"ok": True} and len(calls) == 2

def test_baseten_factory_config():
    llm = baseten.baseten_llm() if C.BASETEN_API_KEY else None
    if llm:
        assert llm.model == "meta-models/muse-spark-open-1026" and llm.auth_scheme == "Api-Key" and llm.max_tokens >= 8000
