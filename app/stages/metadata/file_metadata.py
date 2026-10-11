# the PDF's own info dictionary: often junk, so it ranks last
import re
from functools import cache

import settings
import yaml

from stages.metadata.candidates import SourceResult

# a buyer's stamp in brackets at the end: "Learning Python (for Someone Buyer)"
STAMP = re.compile(r"\([^()]{3,}\)$")
# a file name, not a title: one word with an extension ("scan-0042.pdf"); a title has spaces ("Learning Node.js")
FILE_NAME = re.compile(r"^\S+\.[a-z0-9]{2,5}$")


# values that name the tool or a shop copy rather than the book
@cache
def _junk() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "metadata.yaml").read_text())["pdf_info"]


def is_junk(value: str, file_names: list[str]) -> bool:
    stem = value.strip().lower()
    names = {n.rsplit(".", 1)[0].lower() for n in file_names}
    w = _junk()
    return (not stem or stem in names or STAMP.search(stem) is not None
            or FILE_NAME.match(stem) is not None or stem.startswith(tuple(w["pdf_info_junk"])))


# every file's info dictionary and XMP packet, in file order; the first usable value of each kind is the candidate
def read(infos: list[dict], file_names: list[str], xmps: list[dict] | None = None) -> SourceResult:
    out = SourceResult("file_metadata", covers=("title", "authors", "made_with"))
    titles = [(i.get("Title", ""), "PDF info Title") for i in infos] + [(x.get("title", ""), "XMP dc:title")
                                                                       for x in xmps or []]
    if found := next(((t, why) for t, why in titles if t and not is_junk(t, file_names)), None):
        out.add("title", found[0].strip(), 0.3, found[1])
    authors = [([a.strip() for a in re.split(r"[;,&]", i.get("Author", "")) if a.strip()], "PDF info Author")
               for i in infos if i.get("Author") and not is_junk(i["Author"], file_names)]
    authors += [(x["creators"], "XMP dc:creator") for x in xmps or [] if x.get("creators")
                and not is_junk(", ".join(x["creators"]), file_names)]
    if authors:
        out.add("authors", authors[0][0], 0.3, authors[0][1])
    # the tools that wrote the files, as they name themselves: a scanner's own layout tells how its pages are built
    tools = list(dict.fromkeys(i[k].strip() for i in infos for k in ("Producer", "Creator")
                               if (i.get(k) or "").strip()))
    if tools:
        out.add("made_with", tools, 1.0, "PDF info Producer and Creator")
    return out
