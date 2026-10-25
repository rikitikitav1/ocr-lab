# Bundle and report contract

## Bundle layout

```text
<bundle_dir>/                     data/bundles/<book_id>/<run_id>/
├── <slug>.md                     the document (FR-002)
├── images/                       every figure, named <piece_ord>-<n>.<ext>
├── profile.yaml                  resolved profile: knob path -> option, source, evidence
├── structure.json                every node: ord, title, level, parent_ord, pages, unit, pinned (heading found), anchored (written with its comment)
├── report.json                   machine-readable report (schema below)
└── report.md                     short human summary
```

Links in `<slug>.md` are relative (`images/03-002.png`); moving the directory keeps them valid.

## Markdown rules

- `#` book title, a structure node of level N at N + 1, deeper levels relative to the node, never
  past `######`.
- Code blocks fenced with a language tag when the profile's code knob detects one.
- Tables as pipe tables; tables that cannot be pipe tables (merged cells) as HTML tables.
- Notes and sidebars as blockquotes with a bold label (`> **Note:** ...`), never as headings.
- A footnote an engine reads as one as `[^mark]: text`; a footnote an engine set aside as furniture, on a page
  the page layout reads notes on, comes back as a paragraph on its page (`assembly.notes_from_furniture`, on).
- A caption as one italic line (`*Figure 2-1. ...*`).
- A chapter's own list of its sections on its opening page between `<!-- contents -->` and `<!-- /contents -->`,
  one entry a line, so a reader can leave it out.
- Each node whose heading was found starts with an HTML comment
  `<!-- node ord=N level=L parent=P pages=a-b role=service|body -->` (no `parent` at the top) for
  tracing back to the run and slicing the document at any level; `structure.json` lists every node,
  and one with `anchored` false has no comment (a unit at the deepest level writes its found
  headings as paragraphs): its text sits inside the node before it. The engines
  read and the run assembles in pieces (a node of the reading level with the nodes under it), and
  `unit` names the piece holding the node; `service` marks the unnumbered pieces before the first numbered one (a
  preface, an introduction) and after the last (a conclusion, a bibliography, an index), kept in the
  document so a later reader (a RAG loader) can skip them. A letter counts as a number ("Appendix A").
- Every block belongs to one node (`parent_ord` in the run's model.json): `blocks_without_node` and `blocks_in_two`
  (one engine block written by two units, a page read twice) are 0 when the text is cut cleanly;
  `blocks_by_page` counts blocks whose node was set by the page because its title was not found. `reading_level`
  is the tree level the run's pieces were cut at, null for a run made before pieces were cut at a tree level.
  Nothing is marked when the numbering starts after the first 15% of the book's pages, and nothing
  after the last numbered piece when more than 15% of the pages follow it. report.md lists the
  service pieces with their sub-node counts.

## report.json (schema 3)

Numbers only, no verdict label (owner's decision, 2026-10-10). Shares are 0..1; `lost_text` is the
share of the text layer's words (the book's own running heads and rising page numbers left out) missing
from the piece, `extra_text` the share of the piece's words that are not in the layer. Pages whose
layer has fewer than `piece.layer_min_words` words (a cover, a full-page figure) are left out of both;
the words written from them are `layerless_words`. `set_aside_words` are layer words an engine set aside
as furniture beyond the book's own heads. Recognised pages (no usable layer) are measured by the two
engines' word agreement; a recognised page where both engines read fewer than `layer_min_words` words is
a picture page with no agreement value.

```json
{
  "schema": 3,
  "book": {"id": 0, "sha256": [""], "title": "", "pages": 0},
  "run": {"id": 0, "dir": "", "code_hash": "", "engine_builds": {},
          "made_by": [{"code": "", "builds": {}, "languages": [""], "pieces": [0]}]},
  "metadata": {"metadata_version": 0, "structure_version": 0, "structure_sources": {"base": "", "voting": [""]},
               "fields": {}},
  "numbers": {
    "nodes": 0, "pieces": 0, "pieces_done": 0, "pieces_failed": [],
    "lost_text": 0.0, "extra_text": 0.0, "layer_pages": 0, "set_aside_words": 0, "layerless_words": 0,
    "listing_numbers": 0, "lost_words_no_listing": 0,
    "subs": 0, "subs_found": 0, "long_headings": 0, "empty_headings": 0,
    "max_heading_level": 0, "pieces_below_sections": [0], "heading_sources": {},
    "duplicates": 0, "repeated_paragraphs": 0, "out_of_order": 0.0, "nodes_out_of_order": 0, "figures_not_kept": 0, "captions": 0, "captions_in_caption": 0, "captions_in_paragraph": 0, "captions_in_heading": 0, "captions_lost": 0, "running_heads_in_text": 0, "running_heads_glued": 0, "pages_cut": {"contents": [], "cover": []},
    "recognised_pages": 0, "agreement": 0.0, "picture_pages": 0, "empty_engine_pages": {"mineru": 0, "docling": 0},
    "dictionary_share": 0.0,
    "nodes_by_level": {"1": {"nodes": 0, "pinned": 0}},
    "blocks_without_node": 0, "blocks_in_two": 0, "blocks_by_page": 0, "reading_level": 0,
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
  "duplicates": [{"pieces": [0, 0], "text": ""}],
  "languages": {"book": [""], "ocr": [""], "missing": [""]},
  "seconds": {"read": {"docling": 0.0, "mineru": 0.0}, "readings_untimed": 0, "assemble": 0.0, "pages": 0,
              "per_page": {"read_docling": 0.0, "read_mineru": 0.0, "assemble": 0.0, "total": 0.0}},
  "profile_search": "",
  "profile": {"id": 0, "preset": "", "sha256": "", "knobs_applied": {}, "knob_sources": {}, "piece_overrides": {}},
  "scans": [{"pages": [0, 0], "file": 0, "file_pages": [0, 0], "engine": "", "agreement": 0.0, "agreement_min": 0.0,
             "dictionary_words": 0, "dictionary_share": 0.0, "engine_confidence": null}],
  "layer_spacing": [{"file": 0, "letters_p90": 0.0, "words_p10": 0.0, "joined": true}],
  "monospace": {"share": 0.0, "pages": 0, "sampled": 40, "faces": [{"face": "", "letters": 0, "pages": 0, "spread": 0.0}],
                "preset": "default | technical"},
  "pieces": [{"ord": 0, "title": "", "role": "service | body", "pages": "a-b",
                "files": [{"file": 0, "pages": [0, 0]}], "status": "", "errors": [],
                "checks": {"layer_pages": 0, "layer_words": 0, "lost_words": 0, "extra_words": 0,
                           "lost_text": 0.0, "extra_text": 0.0, "set_aside_words": 0, "layerless_words": 0,
                           "listing_numbers": 0, "lost_words_no_listing": 0,
                           "pages": 0, "subs": 0, "subs_found": 0,
                           "subs_missing": [""], "headings": 0, "long_headings": 0, "empty_headings": 0,
                           "title_level": 0, "max_heading_level": 0, "headings_not_below_title": 0,
                           "heading_sources": {},
                           "repeated_paragraphs": 0, "order_anchors": 0, "out_of_order_anchors": 0, "nodes_out_of_order": 0,
                           "out_of_order": 0.0, "running_heads_in_text": 0, "running_heads_glued": 0, "shared_pages": {},
                           "figures": 0, "figures_not_kept": 0, "captions": 0, "captions_in_caption": 0,
                           "captions_in_paragraph": 0, "captions_in_heading": 0, "captions_lost": 0,
                           "recognised_pages": 0, "agreement": 0.0,
                           "agreement_min": 0.0, "dictionary_words": 0, "dictionary_share": 0.0,
                           "passes": {}, "made_by": {"code": "", "builds": {}, "languages": [""]}, "spacing": {}}}]
}
```

`scans` lists the recognised pages in runs of one engine: book and file pages, the engines' word agreement (mean and
least), the share of words a dictionary of the book's languages knows (null for a spaceless language), and the engine's
own confidence, null since neither engine gives one (FR-032). Still to come with their stage: `gpu_seconds`; the knobs a run applied are the `profile` block's `knobs_applied` and `knob_sources`,
the candidates a profile search tries come with that search (US3). `profile_search` says the search was skipped until it is
built.

`layer_spacing` is per file what the pieces' assemblies read of the text layer's spacing (kept per piece under the checks'
`spacing`), null when no piece read that file's layer. `monospace` is the share of the page layout the run started on
(`runs.layout_version_id`), and its `preset` is the run profile's.

`metadata.fields` is every field of the run's metadata version with its source and confidence; a value set by
hand reads source `manual`. A piece's `files` gives its pages in each file's own numbering, for a book split into
files.

`seconds` is what the book cost: each reading's own time, kept with the reading when it was read, so a run that takes
it from the cache still reports it (`readings_untimed` counts readings kept before their time was); the assembly is
the pieces' assembly time; `per_page` divides by the book's pages.

`profile` names the run's profile: `id`, `preset`, `sha256`, `knobs_applied` (run knobs whose value is not the
registry's default), `knob_sources` (where each of them came from: preset, manual) and `piece_overrides` (a piece's own
knob values with source manual and their evidence, set by a rerun with overrides); report.md has a profile row. A run without a
profile id gets the profile of the preset the book knob `run.preset` names, else the one the page layout's monospace share
chooses (`technical`, else `default`); runs on the same values share one profile.

`report.md` is a table of the book's numbers followed by the worst pieces by each of them. A piece is named for
its deep headings (`worst.max_heading_level`) only when they go more than two levels below its own title (`title_level`,
the level its Markdown writes the title at), past its sections and their sub-sections.
