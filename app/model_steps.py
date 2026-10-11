# a model step by its name in config/models.yaml: the provider and model come from there, never from the caller
import json
from functools import cache

import models_client
import settings
import yaml
from engines import card


@cache
def steps() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "models.yaml").read_text())["steps"]


def call(step: str, system: str, user: str) -> str:
    conf = dict(steps()[step])
    provider, model = conf.pop("provider"), conf.pop("model")
    hand = (lambda: card.hand_to(card.OLLAMA)) if provider == "ollama" else None
    return models_client.chat(provider, model, [{"role": "system", "content": system},
                                                {"role": "user", "content": user}], before_call=hand, **conf)


# the first JSON object in a model's answer, prose or fences around it; an answer with none reads as empty
def parse_json(answer: str) -> dict:
    decoder = json.JSONDecoder()
    for start in (i for i, ch in enumerate(answer) if ch == "{"):
        try:
            found, _ = decoder.raw_decode(answer, start)
        except json.JSONDecodeError:
            continue
        if isinstance(found, dict):
            return found
    return {}
