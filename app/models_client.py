# the stand's own model steps; every call is cached so a rerun reads the same answer
import json
from pathlib import Path

import artifacts
import httpx
import net
import openai
import settings
import text_clean
from job_signals import Deferred
from orm.catalogue import ModelCall
from orm.db import Session
from sqlalchemy.dialects.postgresql import insert


# the SDK's own retries are off: net.Transport retries and sets a failing provider aside
def _client(provider: str) -> openai.OpenAI:
    http = httpx.Client(transport=net.Transport(), timeout=httpx.Timeout(600, connect=10))
    if provider == "ollama":
        return openai.OpenAI(base_url=settings.OLLAMA_BASE_URL + "/v1", api_key="ollama", max_retries=0,
                             http_client=http)
    if provider == "cloud":
        if not settings.MODEL_CLOUD_BASE_URL:
            raise Deferred("MODEL_CLOUD_BASE_URL is not set", delay_seconds=600)
        return openai.OpenAI(base_url=settings.MODEL_CLOUD_BASE_URL, api_key=settings.MODEL_CLOUD_API_KEY,
                             max_retries=0, http_client=http)
    raise ValueError(f"unknown model provider {provider!r}")


def request_hash(provider: str, model: str, messages: list[dict], params: dict) -> str:
    return artifacts.input_hash(provider=provider, model=model, messages=messages, params=params)


def _path(key: str) -> Path:
    return Path("model_calls") / key[:2] / f"{key}.json"


# `before_call` runs only when the answer is not kept, so a kept answer never asks for the card
def chat(provider: str, model: str, messages: list[dict], before_call=None, **params) -> str:
    key = request_hash(provider, model, messages, params)
    with Session() as session:
        cached = session.get(ModelCall, key)
    if cached is not None and (settings.DATA_DIR / cached.response_path).exists():
        return text_clean.clean(json.loads((settings.DATA_DIR / cached.response_path).read_text())["content"])
    if before_call is not None:
        before_call()
    try:
        answer = _client(provider).chat.completions.create(model=model, messages=messages, **params)
    except (net.SourceDown, openai.APIConnectionError, openai.RateLimitError, openai.APITimeoutError) as e:
        raise Deferred(f"{provider} unavailable: {e}", delay_seconds=120) from e
    except openai.APIStatusError as e:
        if e.status_code >= 500:
            raise Deferred(f"{provider} answered {e.status_code}", delay_seconds=120) from e
        raise
    content = answer.choices[0].message.content or ""
    path = _path(key)
    artifacts.atomic_write(settings.DATA_DIR / path, {"request": {"provider": provider, "model": model,
                           "messages": messages, "params": params}, "content": content})
    usage = answer.usage
    with Session() as session:
        session.execute(insert(ModelCall).values(
            request_hash=key, provider=provider, model=model, params=params, response_path=str(path),
            tokens_in=usage.prompt_tokens if usage else None, tokens_out=usage.completion_tokens if usage else None,
        ).on_conflict_do_nothing())
        session.commit()
    return text_clean.clean(content)
