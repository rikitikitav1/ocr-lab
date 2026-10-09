# the stand's own model steps; every call is cached so a rerun reads the same answer
import json
from pathlib import Path

import artifacts
import openai
import settings
from job_handlers import Deferred
from orm.catalogue import ModelCall
from orm.db import Session
from sqlalchemy.dialects.postgresql import insert


def _client(provider: str) -> openai.OpenAI:
    if provider == "ollama":
        return openai.OpenAI(base_url=settings.OLLAMA_BASE_URL + "/v1", api_key="ollama", max_retries=0)
    if provider == "cloud":
        if not settings.MODEL_CLOUD_BASE_URL:
            raise Deferred("MODEL_CLOUD_BASE_URL is not set", delay_seconds=600)
        return openai.OpenAI(base_url=settings.MODEL_CLOUD_BASE_URL, api_key=settings.MODEL_CLOUD_API_KEY,
                             max_retries=0)
    raise ValueError(f"unknown model provider {provider!r}")


def request_hash(provider: str, model: str, messages: list[dict], params: dict) -> str:
    return artifacts.input_hash(provider=provider, model=model, messages=messages, params=params)


def _path(key: str) -> Path:
    return Path("model_calls") / key[:2] / f"{key}.json"


def chat(provider: str, model: str, messages: list[dict], **params) -> str:
    key = request_hash(provider, model, messages, params)
    with Session() as session:
        cached = session.get(ModelCall, key)
    if cached is not None and (settings.DATA_DIR / cached.response_path).exists():
        return json.loads((settings.DATA_DIR / cached.response_path).read_text())["content"]
    try:
        answer = _client(provider).chat.completions.create(model=model, messages=messages, **params)
    except (openai.APIConnectionError, openai.RateLimitError, openai.APITimeoutError) as e:
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
    return content
