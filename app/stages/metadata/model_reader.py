# the stand's model reads the title and copyright pages; it never searches, it only reads what it is given
import re

import model_steps
import numerals

from stages.metadata.candidates import SourceResult

READ_FIELDS = ("title", "authors", "edition", "year", "publisher", "series", "volume", "original_title")
# the prompt still asks for credits the stand no longer keeps: trimming it changed the model's other answers
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


# the imprint often sits on the last pages, so the model gets both ends rather than the first stretch only
HEAD_CHARS, TAIL_CHARS = 7000, 5000


def excerpt(text: str) -> str:
    if len(text) <= HEAD_CHARS + TAIL_CHARS:
        return text
    return text[:HEAD_CHARS] + "\n\n[... middle pages left out ...]\n\n" + text[-TAIL_CHARS:]


# a volume is its number, whatever word the book puts before it: "Volume 4", "Band 11", "Том IX"
VOLUME_NUMBER = re.compile(rf"\d+|\b{numerals.ROMAN}\b")


def volume_number(value: str) -> str:
    found = VOLUME_NUMBER.findall(value)
    return found[-1] if found else value


def read(title_text: str) -> SourceResult:
    out = SourceResult("model", covers=READ_FIELDS)
    if len(title_text.strip()) < 50:
        out.failed = "no title page text to read"
        return out
    try:
        parsed = model_steps.parse_json(model_steps.call("metadata_reader", PROMPT, excerpt(title_text)))
    except (ValueError, KeyError) as e:
        out.failed = f"unreadable answer: {e}"
        return out
    volume = volume_number(str(parsed["volume"])) if parsed.get("volume") is not None else None
    for name in READ_FIELDS:
        value = parsed.get(name)
        if name == "edition" and value is not None:
            value = str(value)
            # a series volume read as the edition: "Volume 4" over a book that prints "1st Edition"
            if value == volume:
                continue
        if name == "volume" and value is not None:
            value = volume_number(str(value))
        if name == "authors" and isinstance(value, str):
            value = [value]
        out.add(name, value, 0.5, f"model {model_steps.steps()['metadata_reader']['model']} over title pages")
    return out


def subject(title: str | None, contents: str, blurb: str) -> SourceResult:
    out = SourceResult("model", covers=("subject",))
    text = f"Title: {title or 'unknown'}\n\nContents and first pages:\n{contents[:4000]}\n\nBack cover:\n{blurb[:2000]}"
    parsed = model_steps.parse_json(model_steps.call("subject", SUBJECT_PROMPT, text))
    field, kind = str(parsed.get("field") or "").strip().lower(), str(parsed.get("kind") or "").strip().lower()
    if field and field not in ("field", "what the book is about"):
        model = model_steps.steps()["subject"]["model"]
        out.add("subject", f"{field}, {kind}" if kind else field, 0.5, f"model {model}")
    return out
