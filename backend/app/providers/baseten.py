"""Muse Spark Open on Baseten Model APIs (OpenAI-compatible). No JSON mode; heavy reasoning -> high max_tokens."""
from .. import config as C
from .openai_compat import ChatLLM

def baseten_llm(effort: str | None = None) -> ChatLLM:
    effort = C.BASETEN_REASONING if effort is None else effort
    # Baseten auth is `Authorization: Api-Key <key>` (not Bearer). The model reasons heavily before answering,
    # so the token budget must cover reasoning + answer.
    return ChatLLM("Muse Spark Open (Baseten)", C.BASETEN_BASE_URL, C.BASETEN_API_KEY, C.BASETEN_MODEL,
                   json_mode=False, auth_scheme="Api-Key", system_role="system", max_tokens=C.BASETEN_MAX_TOKENS,
                   extra={"reasoning_effort": effort} if effort else None)
