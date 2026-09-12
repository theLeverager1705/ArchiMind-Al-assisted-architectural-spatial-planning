"""
Provider-agnostic LLM client.

Speaks plain HTTP to Gemini or OpenAI-compatible endpoints so the project has no
heavyweight SDK dependency, and reports clearly when no key is configured rather
than failing at request time.

Design rule for this project: the model is used only for language, never for
geometry or arithmetic. It turns an English brief into a structured requirement
set and writes review prose. Every number it returns is re-validated and clamped
by the engine before anything is drawn.
"""

from __future__ import annotations

import json
import os
import re

import httpx

TIMEOUT = 30.0


def _env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def provider_status() -> dict:
    """What the UI shows in its AI badge."""
    gemini = _env("GEMINI_API_KEY", "GOOGLE_API_KEY")
    openai = _env("OPENAI_API_KEY")
    if gemini:
        return {"available": True, "provider": "gemini",
                "model": _env("GEMINI_MODEL") or "gemini-2.0-flash"}
    if openai:
        return {"available": True, "provider": "openai",
                "model": _env("OPENAI_MODEL") or "gpt-4o-mini"}
    return {"available": False, "provider": "none", "model": "rule-based fallback"}


class AIError(RuntimeError):
    pass


def complete(system: str, user: str, *, json_mode: bool = True,
             max_tokens: int = 1200) -> str:
    """Single completion call. Raises AIError when no provider is configured."""
    status = provider_status()
    if not status["available"]:
        raise AIError("No AI provider configured")

    if status["provider"] == "gemini":
        return _gemini(system, user, status["model"], json_mode, max_tokens)
    return _openai(system, user, status["model"], json_mode, max_tokens)


def _gemini(system: str, user: str, model: str, json_mode: bool, max_tokens: int) -> str:
    key = _env("GEMINI_API_KEY", "GOOGLE_API_KEY")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_tokens,
            **({"responseMimeType": "application/json"} if json_mode else {}),
        },
    }
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(url, params={"key": key}, json=body)
        if r.status_code >= 400:
            raise AIError(f"Gemini {r.status_code}: {r.text[:300]}")
        data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError) as exc:
        raise AIError(f"Unexpected Gemini response: {str(data)[:300]}") from exc


def _openai(system: str, user: str, model: str, json_mode: bool, max_tokens: int) -> str:
    key = _env("OPENAI_API_KEY")
    base = _env("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        **({"response_format": {"type": "json_object"}} if json_mode else {}),
    }
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(f"{base}/chat/completions",
                   headers={"Authorization": f"Bearer {key}"}, json=body)
        if r.status_code >= 400:
            raise AIError(f"OpenAI {r.status_code}: {r.text[:300]}")
        data = r.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise AIError(f"Unexpected OpenAI response: {str(data)[:300]}") from exc


def parse_json(text: str) -> dict:
    """
    Pull a JSON object out of a model response.

    Models wrap JSON in prose or fences often enough that this needs to be
    tolerant, but it never evaluates the text: a failure returns empty and the
    caller falls back to the deterministic parser.
    """
    text = (text or "").strip()
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            out = json.loads(text[start:end + 1])
            return out if isinstance(out, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
