# the PDF's own info dictionary: often junk, so it ranks last
import re

from stages.metadata.candidates import SourceResult

JUNK = re.compile(r"\.(dvi|tex|docx?|indd)$|^microsoft word|^untitled|^myebooks?$|\(for .+\)$", re.IGNORECASE)


def is_junk(value: str, file_names: list[str]) -> bool:
    stem = value.strip().lower()
    names = {n.rsplit(".", 1)[0].lower() for n in file_names}
    return not stem or bool(JUNK.search(stem)) or stem in names


def read(infos: list[dict], file_names: list[str]) -> SourceResult:
    out = SourceResult("file_metadata", covers=("title", "authors"))
    if not infos:
        return out
    first = infos[0]
    title = first.get("Title", "")
    if title and not is_junk(title, file_names):
        out.add("title", title.strip(), 0.3, "PDF info Title")
    author = first.get("Author", "")
    if author and not is_junk(author, file_names):
        names = [a.strip() for a in re.split(r";|,| and ", author) if a.strip()]
        out.add("authors", names, 0.3, "PDF info Author")
    return out
