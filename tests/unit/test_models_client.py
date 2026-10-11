from types import SimpleNamespace

import models_client
import openai
import pytest
from job_signals import Deferred

from tests.real_db import needs_db

pytestmark = needs_db


class _Fake:
    def __init__(self, answers):
        self.calls = 0
        self.answers = answers
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))],
                               usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2))


def test_second_identical_call_reads_the_cache(stand, monkeypatch):
    fake = _Fake(["first"])
    monkeypatch.setattr(models_client, "_client", lambda provider: fake)
    messages = [{"role": "user", "content": "title?"}]
    handed = []
    assert models_client.chat("ollama", "m", messages, before_call=lambda: handed.append(1), temperature=0) == "first"
    assert models_client.chat("ollama", "m", messages, before_call=lambda: handed.append(1), temperature=0) == "first"
    assert fake.calls == 1 and handed == [1]


def test_unreachable_provider_defers(stand, monkeypatch):
    fake = _Fake([openai.APIConnectionError(request=SimpleNamespace(method="POST", url="x"))])
    monkeypatch.setattr(models_client, "_client", lambda provider: fake)
    with pytest.raises(Deferred):
        models_client.chat("ollama", "m", [{"role": "user", "content": "x"}])


def test_a_provider_failing_every_retry_is_set_aside_and_the_call_defers(stand, monkeypatch):
    import httpx
    import net
    import settings

    calls = []

    def down(request):
        calls.append(request.url.path)
        return httpx.Response(503)

    def client(provider):
        http = httpx.Client(transport=net.Transport(httpx.MockTransport(down)))
        return openai.OpenAI(base_url="https://api.provider.test/v1", api_key="k", max_retries=0, http_client=http)

    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    monkeypatch.setattr(models_client, "_client", client)
    monkeypatch.setattr(settings, "MODEL_CLOUD_BASE_URL", "https://api.provider.test/v1")
    net.reset()
    try:
        with pytest.raises(Deferred):
            models_client.chat("cloud", "m", [{"role": "user", "content": "set aside?"}])
        assert len(calls) == 4 and "api.provider.test" in net.inactive()
    finally:
        net.reset()


def test_the_real_client_goes_through_the_net_door():
    client = models_client._client("ollama")
    assert isinstance(client._client._transport, models_client.net.Transport)
