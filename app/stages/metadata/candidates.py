from dataclasses import dataclass, field

FIELDS = ("title", "authors", "translators", "illustrators", "edition", "year", "languages", "publisher", "series",
          "volume", "isbn", "original_title", "original_year", "original_isbn", "subject", "pages", "editions")
# owner's rule: these must be found for every book
REQUIRED = ("title", "authors", "languages", "subject", "pages")
# looked for everywhere, by title too when there is no ISBN; empty only when no source has them
SOUGHT = ("publisher", "year", "isbn")
# not every book has these; an empty one is not a gap in the record
OPTIONAL = tuple(f for f in FIELDS if f not in REQUIRED + SOUGHT)


@dataclass
class Candidate:
    field: str
    value: object
    source: str
    confidence: float
    evidence: str = ""


@dataclass
class SourceResult:
    source: str
    candidates: list[Candidate] = field(default_factory=list)
    # fields this source can answer; an unknown field lists every source that could have
    covers: tuple[str, ...] = ()
    failed: str | None = None

    def add(self, name: str, value, confidence: float, evidence: str = "") -> None:
        if value in (None, "", []):
            return
        self.candidates.append(Candidate(name, value, self.source, confidence, evidence))
