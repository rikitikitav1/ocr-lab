# Bundle and report contract

## Bundle layout

```text
<bundle_dir>/                     data/bundles/<book_id>/<run_id>/
├── <slug>.md                     the document (FR-002)
├── images/                       every figure, named <chapter_ord>-<n>.<ext>
├── profile.yaml                  resolved profile: knob path -> option, source, evidence
├── report.json                   machine-readable report (schema below)
└── report.md                     short human summary
```

Links in `<slug>.md` are relative (`images/03-002.png`); moving the directory keeps them valid.

## Markdown rules

- `#` book title, `##` chapters (or parts when the book has parts, then chapters at `###`),
  deeper levels relative to the chapter, never past `######`.
- Code blocks fenced with a language tag when the profile's code knob detects one.
- Tables as pipe tables; tables that cannot be pipe tables (merged cells) as HTML tables.
- Notes and sidebars as blockquotes with a bold label (`> **Note:** ...`), never as headings.
- Each chapter starts with an HTML comment `<!-- chapter ord=N pages=a-b role=service|body -->` for
  tracing back to the run; `service` marks the unnumbered chapters before the first numbered one (a
  preface, an introduction) and after the last (a conclusion, a bibliography, an index), kept in the
  document so a later reader (a RAG loader) can skip them. A letter counts as a number ("Appendix A").
  Nothing is marked when the numbering starts after the first 15% of the book's pages, and nothing
  after the last numbered chapter when more than 15% of the pages follow it. report.md lists the
  service chapters with their toc sub-entry counts.

## report.json (schema 2)

Numbers only, no verdict label (owner's decision, 2026-10-10). Shares are 0..1; `lost_text` is the
share of the text layer's words (the book's own running heads and rising page numbers left out) missing
from the chapter, `extra_text` the share of the chapter's words that are not in the layer. Pages whose
layer has fewer than `chapter.layer_min_words` words (a cover, a full-page figure) are left out of both;
the words written from them are `layerless_words`. `set_aside_words` are layer words an engine set aside
as furniture beyond the book's own heads. Recognised pages (no usable layer) are measured by the two
engines' word agreement; a recognised page where both engines read fewer than `layer_min_words` words is
a picture page with no agreement value.

```json
{
  "schema": 2,
  "book": {"id": 0, "sha256": [""], "title": "", "pages": 0},
  "run": {"id": 0, "dir": "", "code_hash": "", "engine_builds": {},
          "made_by": [{"code": "", "builds": {}, "languages": [""], "chapters": [0]}]},
  "metadata": {"metadata_version": 0, "toc_version": 0, "toc_sources": {"base": "", "voting": [""]},
               "fields": {}},
  "numbers": {
    "toc_entries": 0, "chapters": 0, "chapters_done": 0, "chapters_failed": [],
    "lost_text": 0.0, "extra_text": 0.0, "layer_pages": 0, "set_aside_words": 0, "layerless_words": 0,
    "subs": 0, "subs_found": 0, "long_headings": 0, "empty_headings": 0,
    "max_heading_level": 0, "chapters_below_sections": [0], "heading_sources": {},
    "duplicates": 0, "repeated_paragraphs": 0, "out_of_order": 0.0, "running_heads_in_text": 0, "pages_cut": {"contents": [], "cover": []},
    "recognised_pages": 0, "agreement": 0.0, "picture_pages": 0, "dictionary_share": 0.0,
    "worst": {"lost_text": [{"ord": 0, "title": "", "lost_text": 0.0}],
              "extra_text": [{"ord": 0, "title": "", "extra_text": 0.0}],
              "agreement": [{"ord": 0, "title": "", "agreement": 0.0}],
              "max_heading_level": [{"ord": 0, "title": "", "max_heading_level": 0}],
              "out_of_order": [{"ord": 0, "title": "", "out_of_order": 0.0}],
              "repeated_paragraphs": [{"ord": 0, "title": "", "repeated_paragraphs": 0}],
              "long_headings": [{"ord": 0, "title": "", "long_headings": 0}],
              "subs_missing": [{"ord": 0, "title": "", "missing": 0}]}
  },
  "images": {"figures": 0, "files": 0, "links": 0, "broken_links": 0, "unreferenced_files": 0},
  "duplicates": [{"chapters": [0, 0], "text": ""}],
  "languages": {"book": [""], "ocr": [""], "missing": [""]},
  "seconds": {"read": {"docling": 0.0, "mineru": 0.0}, "readings_untimed": 0, "assemble": 0.0, "pages": 0,
              "per_page": {"read_docling": 0.0, "read_mineru": 0.0, "assemble": 0.0, "total": 0.0}},
  "profile_search": "",
  "profile": {"id": 0, "preset": "", "sha256": "", "knobs_applied": {}, "chapter_overrides": {}},
  "chapters": [{"ord": 0, "title": "", "role": "service | body", "pages": "a-b",
                "files": [{"file": 0, "pages": [0, 0]}], "status": "", "errors": [],
                "checks": {"layer_pages": 0, "layer_words": 0, "lost_words": 0, "extra_words": 0,
                           "lost_text": 0.0, "extra_text": 0.0, "set_aside_words": 0, "layerless_words": 0,
                           "pages": 0, "subs": 0, "subs_found": 0,
                           "subs_missing": [""], "headings": 0, "long_headings": 0, "empty_headings": 0,
                           "title_level": 0, "max_heading_level": 0, "headings_not_below_title": 0,
                           "heading_sources": {},
                           "repeated_paragraphs": 0, "order_anchors": 0, "out_of_order_anchors": 0,
                           "out_of_order": 0.0, "running_heads_in_text": 0, "shared_pages": {},
                           "figures": 0, "figures_not_kept": 0, "recognised_pages": 0, "agreement": 0.0,
                           "agreement_min": 0.0, "dictionary_words": 0, "dictionary_share": 0.0,
                           "passes": {}, "made_by": {"code": "", "builds": {}, "languages": [""]}}}]
}
```

Still to come with their stages: `scans` (engine confidence per
range, FR-032), `knobs_tried` (US2-US4), `gpu_seconds`. `profile_search` says the search was skipped until it is
built.

`metadata.fields` is every field of the run's metadata version with its source and confidence; a value set by
hand reads source `manual`. A chapter's `files` gives its pages in each file's own numbering, for a book split into
files.

`seconds` is what the book cost: each reading's own time, kept with the reading when it was read, so a run that takes
it from the cache still reports it (`readings_untimed` counts readings kept before their time was); the assembly is
the chapters' assembly time; `per_page` divides by the book's pages.

`profile` names the run's profile: `id`, `preset`, `sha256`, `knobs_applied` (run knobs whose value is not the
registry's default) and `chapter_overrides` (a chapter's own knob values, set by a rerun with overrides). A run without a
profile id asks for none and gets the default preset's profile; runs on the same values share one profile.

`report.md` is a table of the book's numbers followed by the worst chapters by each of them. A chapter is named for
its deep headings (`worst.max_heading_level`) only when they go more than two levels below its own title (`title_level`,
the level its Markdown writes the title at), past its sections and their sub-sections.
