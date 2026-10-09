# the stand's model reads the title and copyright pages; it never searches, it only reads what it is given
import json
import re
from functools import cache

import models_client
import settings
import yaml

from stages.metadata.candidates import SourceResult

READ_FIELDS = ("title", "authors", "translators", "illustrators", "edition", "year", "publisher", "series", "volume",
               "original_title", "original_year")
PROMPT = (
    "You read the title and copyright pages of a book and return JSON only, no prose. Keys: title (string), "
    "authors (list of strings), translators (list of strings, empty if not a translation), illustrators (list of "
    "strings, empty if none credited), edition (integer or "
    "null), year (integer or null: the year of this edition or translation, not of the original), publisher "
    "(string or null), series (string or null, a publisher's book series or a multi-volume work), volume (string "
    "or null), original_title (string or null: the title in the original language), original_year (integer or "
    "null: when the original was first published). When a name or a title appears in two scripts, give it as "
    "written in the language of the book. Use only what the pages say; put null where they do not."
)
# no example topics, and two keys rather than a pattern: a weak model copied whatever pattern it was shown
SUBJECT_PROMPT = (
    "Read the pages below and return JSON only: {\"field\": what the book is about, a few words; "
    "\"kind\": textbook, novel, reference, popular science, children's book, poetry, or another kind}. "
    "English, lower case. Base it only on these pages."
)


@cache
def steps() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "models.yaml").read_text())["steps"]


def _call(step: str, system: str, user: str) -> str:
    conf = dict(steps()[step])
    provider, model = conf.pop("provider"), conf.pop("model")
    if provider == "ollama":
        from engines import card

        card.hand_to(card.OLLAMA)
    return models_client.chat(provider, model, [{"role": "system", "content": system},
                                                {"role": "user", "content": user}], **conf)


def _json(answer: str) -> dict:
    m = re.search(r"\{.*\}", answer, re.S)
    return json.loads(m.group(0)) if m else {}


# the imprint often sits on the last pages, so the model gets both ends rather than the first stretch only
HEAD_CHARS, TAIL_CHARS = 7000, 5000


def excerpt(text: str) -> str:
    if len(text) <= HEAD_CHARS + TAIL_CHARS:
        return text
    return text[:HEAD_CHARS] + "\n\n[... middle pages left out ...]\n\n" + text[-TAIL_CHARS:]


def read(title_text: str) -> SourceResult:
    out = SourceResult("model", covers=READ_FIELDS)
    if len(title_text.strip()) < 50:
        out.failed = "no title page text to read"
        return out
    try:
        parsed = _json(_call("metadata_reader", PROMPT, excerpt(title_text)))
    except (ValueError, KeyError) as e:
        out.failed = f"unreadable answer: {e}"
        return out
    for name in READ_FIELDS:
        value = parsed.get(name)
        if name == "edition" and value is not None:
            value = str(value)
        if name in ("authors", "translators", "illustrators") and isinstance(value, str):
            value = [value]
        out.add(name, value, 0.5, f"model {steps()['metadata_reader']['model']} over title pages")
    return out


def subject(title: str | None, contents: str, blurb: str) -> SourceResult:
    out = SourceResult("model", covers=("subject",))
    text = f"Title: {title or 'unknown'}\n\nContents and first pages:\n{contents[:4000]}\n\nBack cover:\n{blurb[:2000]}"
    parsed = _json(_call("subject", SUBJECT_PROMPT, text))
    field, kind = str(parsed.get("field") or "").strip().lower(), str(parsed.get("kind") or "").strip().lower()
    if field and field not in ("field", "what the book is about"):
        out.add("subject", f"{field}, {kind}" if kind else field, 0.5, f"model {steps()['subject']['model']}")
    return out
