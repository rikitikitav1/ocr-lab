# Status

Where each step of the feature stands. The steps come from the
[spec](../specs/001-pdf-book-to-markdown/spec.md); what is not handled yet, book by book, is in
[limitations.md](limitations.md).

| step | what | state |
|---|---|---|
| P0 | the stand, a catalogue of books, complete metadata for a submitted PDF | done |
| P1 | structure from every source, assembly piece by piece, Markdown bundle, quality report | in progress: built and measured; a raw run of 43 books is in [experiments](experiments/2026-10-11_raw-run.md), open items in limitations.md |
| P2 | resuming interrupted runs at piece level, cleanup | planned (resume, rerun and retry already exist, built for P1) |
| P3 | the stand picks the knob profile per book by measuring candidates | planned (the knob registry, presets and profiles already exist, built for P1) |
| P4 | evaluation set of books and gates for changes that affect every book | planned (the structure, metadata and element golds already run by hand, built for P1) |
| P5 | doors for an external agent to add new knobs | planned |
