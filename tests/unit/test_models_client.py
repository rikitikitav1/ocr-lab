from types import SimpleNamespace

import models_client
import openai
import pytest
from job_handlers import Deferred

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
    assert models_client.chat("ollama", "m", messages, temperature=0) == "first"
    assert models_client.chat("ollama", "m", messages, temperature=0) == "first"
    assert fake.calls == 1


def test_unreachable_provider_defers(stand, monkeypatch):
    fake = _Fake([openai.APIConnectionError(request=SimpleNamespace(method="POST", url="x"))])
    monkeypatch.setattr(models_client, "_client", lambda provider: fake)
    with pytest.raises(Deferred):
        models_client.chat("ollama", "m", [{"role": "user", "content": "x"}])
