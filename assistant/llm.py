"""LLM client: OpenRouter first, Gemini (google-genai) as backup.

Retries with backoff on 429/5xx, then moves to the next provider/model, and
keeps a persistent prompt cache so repeated questions (and the demo) never
depend on a live call.
"""
import hashlib
import json
import logging
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from functools import partial

import httpx
from django.conf import settings

log = logging.getLogger(__name__)

RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_client = None


class LLMError(Exception):
    pass


class _Retryable(Exception):
    """A failure worth retrying (rate limit, overload, timeout)."""


def get_client():
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise LLMError("GEMINI_API_KEY is not set.")
        from google import genai
        from google.genai import types

        # Retries are handled in _call(); disable the SDK's own so they don't stack.
        _client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=60_000, retry_options=types.HttpRetryOptions(attempts=1)),
        )
    return _client


def cache_key(prompt, system, json_mode):
    # Provider-independent: an answer cached from either provider is reused.
    payload = json.dumps([settings.GEMINI_MODEL, system or "", prompt, json_mode])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key):
    from .models import CacheEntry

    entry = CacheEntry.objects.filter(key=key).first()
    return entry.response if entry else None


def _cache_put(key, text, model):
    from .models import CacheEntry

    CacheEntry.objects.update_or_create(key=key, defaults={"model": model[:100], "response": text})


def _call_openrouter(prompt, system, json_mode, temperature):
    models = settings.OPENROUTER_MODELS
    body = {
        "model": models[0],
        "models": models,  # OpenRouter routes to the next model if one is unavailable
        "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "CodeLens RAG",
    }
    try:
        resp = httpx.post(OPENROUTER_URL, json=body, headers=headers, timeout=60)
    except httpx.HTTPError as e:
        raise _Retryable(f"OpenRouter request failed: {e}") from e
    try:
        data = resp.json()
    except ValueError:
        data = {}
    err = data.get("error") if isinstance(data, dict) else None
    if resp.status_code in RETRYABLE_CODES or (err and err.get("code") in RETRYABLE_CODES):
        raise _Retryable(f"OpenRouter error {resp.status_code}: {(err or {}).get('message', resp.text[:200])}")
    if resp.status_code >= 400 or err:
        raise LLMError(f"OpenRouter error {resp.status_code}: {(err or {}).get('message', resp.text[:200])}")
    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    if not text:
        raise _Retryable("OpenRouter returned an empty response.")
    return text, f"openrouter:{data.get('model') or models[0]}"


def _call_gemini(model, prompt, system, json_mode, temperature):
    from google.genai import errors, types

    config = types.GenerateContentConfig(
        temperature=temperature,
        system_instruction=system or None,
        response_mime_type="application/json" if json_mode else None,
    )
    try:
        resp = get_client().models.generate_content(model=model, contents=prompt, config=config)
    except errors.APIError as e:
        message = f"Gemini API error {getattr(e, 'code', '')}: {getattr(e, 'message', e)}"
        if getattr(e, "code", None) in RETRYABLE_CODES:
            raise _Retryable(message) from e
        raise LLMError(message) from e
    except Exception as e:  # network hiccups / timeouts
        raise _Retryable(f"Gemini request failed: {e}") from e
    text = (resp.text or "").strip()
    if not text:
        raise _Retryable("Gemini returned an empty response.")
    return text, f"gemini:{model}"


def _attempts():
    """Ordered (label, fn(prompt, system, json_mode, temperature)): OpenRouter first, Gemini as backup."""
    plan = []
    if settings.OPENROUTER_API_KEY:
        plan.append(("openrouter", _call_openrouter))
    if settings.GEMINI_API_KEY:
        plan.append((f"gemini:{settings.GEMINI_MODEL}", partial(_call_gemini, settings.GEMINI_MODEL)))
        if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL != settings.GEMINI_MODEL:
            plan.append((f"gemini:{settings.GEMINI_FALLBACK_MODEL}", partial(_call_gemini, settings.GEMINI_FALLBACK_MODEL)))
    if settings.OPENROUTER_API_KEY and len(plan) > 1:
        plan.append(("openrouter (retry)", _call_openrouter))
    if not plan:
        raise LLMError("No LLM configured. Set OPENROUTER_API_KEY or GEMINI_API_KEY in .env.")
    return plan


def _attempt(fn, prompt, system, json_mode, temperature):
    """One provider call; for JSON requests an unparseable reply counts as a failure."""
    text, model = fn(prompt, system, json_mode, temperature)
    if json_mode:
        try:
            _parse_json(text)
        except ValueError as e:
            raise _Retryable(f"{model} returned invalid JSON") from e
    return text, model


def _call(prompt, system, json_mode, temperature, deadline=None, hedge_after=None):
    """Race providers for a reliable answer. Returns (text, model_used).

    The first provider starts at once. The next one starts as soon as a running
    one fails, or after `hedge_after` seconds without an answer (hedging), so a
    slow model is overtaken instead of waited on. The first valid answer wins;
    after `deadline` seconds we give up with LLMError.
    """
    plan = _attempts()
    deadline = settings.LLM_DEADLINE if deadline is None else deadline
    hedge_after = settings.LLM_HEDGE_AFTER if hedge_after is None else hedge_after
    give_up_at = time.monotonic() + deadline
    pool = ThreadPoolExecutor(max_workers=len(plan), thread_name_prefix="llm")
    running, errors = {}, []
    next_i, last_start = 0, 0.0

    def start_next():
        nonlocal next_i, last_start
        label, fn = plan[next_i]
        next_i += 1
        last_start = time.monotonic()
        running[pool.submit(_attempt, fn, prompt, system, json_mode, temperature)] = label

    try:
        start_next()
        while running:
            now = time.monotonic()
            if now >= give_up_at:
                break
            timeout = give_up_at - now
            if next_i < len(plan):
                timeout = min(timeout, max(0.0, last_start + hedge_after - now))
            done, _ = wait(running, timeout=max(timeout, 0.01), return_when=FIRST_COMPLETED)
            for fut in done:
                label = running.pop(fut)
                try:
                    return fut.result()
                except Exception as e:  # _Retryable, LLMError, network: try someone else
                    errors.append(f"{label}: {e}")
                    log.warning("LLM %s failed: %s", label, e)
            hedge_due = time.monotonic() - last_start >= hedge_after
            if next_i < len(plan) and (done or hedge_due or not running):
                if not done and running:
                    log.warning("LLM %s is slow; also asking %s", list(running.values()), plan[next_i][0])
                start_next()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # slow losers finish in the background
    if time.monotonic() >= give_up_at:
        raise LLMError(f"No model answered within {deadline:.0f}s" + (f" ({errors[-1]})" if errors else "."))
    raise LLMError(errors[-1] if errors else "LLM request failed.")


def generate(prompt, system=None, use_cache=True, temperature=0.2):
    """Plain-text generation. Returns (text, from_cache)."""
    key = cache_key(prompt, system, False)
    if use_cache and (hit := _cache_get(key)) is not None:
        return hit, True
    text, model = _call(prompt, system, False, temperature)
    if use_cache:
        _cache_put(key, text, model)
    return text, False


def _parse_json(text):
    text = re.sub(r"^\s*<think>.*?</think>", "", text.strip(), flags=re.S).strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some models add a sentence before/after the object; take the outermost {...}.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object found")
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def generate_json(prompt, system=None, use_cache=True, temperature=0.2):
    """JSON generation with one repair retry. Returns (dict, from_cache)."""
    key = cache_key(prompt, system, True)
    if use_cache and (hit := _cache_get(key)) is not None:
        try:
            return _parse_json(hit), True
        except ValueError:
            pass  # corrupt cache entry; regenerate
    # _call already rejects unparseable replies and moves on to another model.
    text, model = _call(prompt, system, True, temperature)
    data = _parse_json(text)
    if use_cache:
        _cache_put(key, text, model)
    return data, False
