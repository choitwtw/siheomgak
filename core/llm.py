"""Claude API 연결부.

- API 키: 환경변수 ANTHROPIC_API_KEY → st.secrets["ANTHROPIC_API_KEY"] 순서로 찾는다.
- 키가 없거나 호출이 실패하면 LLMError 를 던지고, 호출하는 쪽에서 규칙 기반 대체 모드로 넘어간다.
  (시연 중 어떤 경우에도 앱이 멈추지 않도록)
"""
from __future__ import annotations

import json
import os
import string
import time
from pathlib import Path

from .config import LLM_EFFORT, LLM_MAX_TOKENS, LLM_MODEL, LLM_TIMEOUT_SEC

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
LAST_ERROR: str | None = None
_LAST_FAIL = 0.0
COOLDOWN_SEC = 90   # 호출이 실패하면 잠시 AI 호출을 쉬고 바로 대체 모드로 (화면이 느려지지 않게)


class LLMError(RuntimeError):
    pass


def load_prompt(name: str, **values) -> str:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    return string.Template(text).safe_substitute(**values)


def get_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    try:
        import streamlit as st
        key = st.secrets.get("ANTHROPIC_API_KEY")  # secrets.toml 이 없으면 예외
        return str(key).strip() if key else None
    except Exception:  # noqa: BLE001
        return None


def has_key() -> bool:
    return bool(get_api_key())


def available() -> bool:
    """키가 있고, 최근에 호출이 실패하지 않았으면 True"""
    return has_key() and (time.time() - _LAST_FAIL > COOLDOWN_SEC)


def status() -> tuple[str, bool]:
    if not has_key():
        return "대체 모드 · 규칙 기반 (API 키 없음)", False
    if not available():
        return "대체 모드 · AI 호출 실패로 규칙 기반 사용 중", False
    return f"AI 모드 · Claude ({LLM_MODEL})", True


_client = None


def _get_client():
    global _client
    key = get_api_key()
    if not key:
        raise LLMError("API 키가 설정되어 있지 않습니다.")
    if _client is None or getattr(_client, "_sg_key", None) != key:
        import anthropic
        _client = anthropic.Anthropic(api_key=key, timeout=LLM_TIMEOUT_SEC, max_retries=1)
        _client._sg_key = key
    return _client


def _create(system: str, user: str, output_format: dict | None):
    """Messages API 호출. 서버 측 거절 대체(fallbacks) 를 먼저 시도하고, 지원하지 않으면 일반 호출."""
    import anthropic
    client = _get_client()
    params = dict(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": LLM_EFFORT, **({"format": output_format} if output_format else {})},
    )
    try:
        return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
    except (TypeError, anthropic.BadRequestError):
        return client.messages.create(**params)


def _text_of(resp) -> str:
    if getattr(resp, "stop_reason", None) == "refusal":
        raise LLMError("모델이 요청을 처리하지 않았습니다(refusal).")
    if getattr(resp, "stop_reason", None) == "max_tokens":
        raise LLMError("응답이 길이 제한에서 잘렸습니다.")
    texts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    if not texts:
        raise LLMError("응답에 텍스트가 없습니다.")
    return "".join(texts).strip()


def _guard(fn):
    def wrapper(*a, **k):
        global LAST_ERROR, _LAST_FAIL
        try:
            out = fn(*a, **k)
            LAST_ERROR = None
            return out
        except LLMError as e:
            LAST_ERROR = str(e)
            _LAST_FAIL = time.time()
            raise
        except Exception as e:  # noqa: BLE001  (네트워크·인증·SDK 오류 모두 대체 모드로)
            LAST_ERROR = f"{type(e).__name__}: {str(e)[:200]}"
            _LAST_FAIL = time.time()
            raise LLMError(LAST_ERROR) from e
    return wrapper


@_guard
def call_json(system: str, user: str, schema: dict) -> dict:
    resp = _create(system, user, {"type": "json_schema", "schema": schema})
    text = _text_of(resp)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON 형식이 아닌 응답: {text[:80]}") from e


@_guard
def call_text(system: str, user: str) -> str:
    return _text_of(_create(system, user, None))
