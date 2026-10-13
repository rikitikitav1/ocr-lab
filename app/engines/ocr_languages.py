# which book languages Docling's Tesseract can read, and fetching the data for one more through the outside door
from functools import cache

import artifacts
import net
import settings
import yaml

# a traineddata file is a few megabytes at least; anything smaller is an error page saved by mistake
MIN_BYTES = 100_000


@cache
def conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "tesseract_languages.yaml").read_text())


def data_dir():
    return settings.DATA_DIR / "tessdata"


def installed_codes() -> set[str]:
    return {p.stem for p in data_dir().glob("*.traineddata")}


def codes(language: str) -> list[str]:
    return list(conf()["codes"].get(language, []))


def installed(language: str) -> bool:
    found = codes(language)
    return bool(found) and set(found) <= installed_codes()


# the Tesseract codes for a book's languages in their order, the always-given ones last, missing ones left out
def tesseract_codes(languages: list[str]) -> list[str]:
    out = [c for lang in languages if installed(lang) for c in codes(lang)] + list(conf()["always"])
    return list(dict.fromkeys(out))


def listing() -> dict:
    return {"installed": sorted(lang for lang in conf()["codes"] if installed(lang)),
            "installable": sorted(lang for lang in conf()["codes"] if not installed(lang))}


def install(language: str) -> dict:
    found = codes(language)
    if not found:
        raise LookupError(f"no Tesseract data known for language {language!r}; known: {', '.join(conf()['codes'])}")
    fetched = []
    for code in found:
        if code in installed_codes():
            continue
        got = net.get(conf()["source"].format(code=code), follow_redirects=True, timeout=300)
        got.raise_for_status()
        body = got.content
        if len(body) < MIN_BYTES:
            raise RuntimeError(f"{code}.traineddata came back as {len(body)} bytes, not language data")
        artifacts.atomic_write(data_dir() / f"{code}.traineddata", body)
        fetched.append(code)
    return {"language": language, "codes": found, "fetched": fetched, **listing()}
