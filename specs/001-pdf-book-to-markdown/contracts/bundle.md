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
- Each chapter starts with an HTML comment `<!-- chapter ord=N pages=a-b -->` for tracing back to
  the run.

## report.json (schema 1)

```json
{
  "schema": 1,
  "book": {"id": 0, "sha256": "", "title": "", "pages": 0},
  "run": {"id": 0, "dir": "", "code_hash": "", "engine_builds": {}, "profile_sha256": ""},
  "verdict": "ok | dirty | bad",
  "reasons": [{"code": "", "chapter": null, "detail": ""}],
  "structure": {
    "toc_entries": 0, "chapters_found": 0, "chapter_recall": 0.0, "level_agreement": 0.0,
    "headings_by_source": {"bookmarks": 0, "printed_contents": 0, "numbering": 0,
                           "typography": 0, "catalogue": 0, "model": 0},
    "max_level": 0, "chapter_below_own_section": 0, "flat_chapters": 0
  },
  "text": {"layer_pages": 0, "layer_f1": 0.0},
  "scans": {"pages": 0, "engine_agreement": 0.0, "dictionary_share": 0.0,
            "by_range": [{"pages": "a-b", "engine_agreement": 0.0, "dictionary_share": 0.0}]},
  "images": {"files": 0, "links": 0, "broken_links": 0, "unreferenced_files": 0,
             "decorative_dropped": 0},
  "duplicates": {"pages_removed": 0},
  "chapters": [{"ord": 0, "title": "", "verdict": "", "reasons": [], "checks": {}}],
  "knobs_applied": {"knob.path": {"option": "", "source": "", "chapters": "all | [..]"}},
  "profile_search": {"candidates": 0, "kept": 0, "model_calls": 0},
  "seconds": {"total": 0, "by_stage": {}}, "gpu_seconds": 0
}
```

Book verdict is the worst of `chapters[].verdict` and the whole-book checks; `reasons` names the
chapters and checks that set it.
