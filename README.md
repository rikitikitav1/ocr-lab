# ocr-lab

ocr-lab turns an e-book into a structured document whose sections match the book. You feed it a PDF
(text or scanned, one file or several), pick an output format, and get back Markdown with the book's
chapters at the right heading levels, a folder of images linked from the text, and a report that
says how good the result is. The first output format is Markdown; DoclingDocument for RAG comes later,
as do EPUB and HTML inputs.

Every book is different, so there is no single setting for all of them. Each book gets its own profile
of knobs (where the table of contents comes from, how a chapter title, a code block, a sidebar, a table
or a running head is recognised), the stand picks the values by measuring them, and every stage leaves
a file behind, so a run can be traced step by step and resumed after a crash.

The rules the project keeps are in the [constitution](.specify/memory/constitution.md); the feature
being built is specified in [specs/001-pdf-book-to-markdown](specs/001-pdf-book-to-markdown/spec.md).

## Status

| step | what | state |
|---|---|---|
| P0 | the stand, a catalogue of books, complete metadata for a submitted PDF | done |
| P1 | table of contents from every source, chapter-by-chapter assembly, Markdown bundle, quality report | next |
| P2 | resuming interrupted runs at chapter level, cleanup | planned |
| P3 | the stand picks the knob profile per book by measuring candidates | planned |
| P4 | evaluation set of books and gates for changes that affect every book | planned |
| P5 | doors for an external agent to add new knobs | planned |

## What happens to a PDF today

<details open>
<summary>Diagram: from a submitted PDF to a catalogue record with metadata</summary>

![After a PDF is fed: catalogue record and metadata](diagrams/intake.drawio.svg)

</details>

1. **Submit.** `POST /v1/books` (or the MCP tool `add_book`) takes paths on the shelf or under
   `data/inbox`, in order; `POST /v1/books/upload` takes the bytes. A book is identified by the hashes
   of its files in order, so the same files submitted again return the same book and nothing is queued.
   Two editions are two books. A book split into several files is one submission; volumes of a series
   are separate books linked by the `series` and `volume` fields.
2. **Intake** (CPU lane). Per page: is there a text layer. Per file: bookmarks. In the first pages:
   printed contents lines with dot leaders. The result is kept as `probe.json` and reused while the
   files are unchanged.
3. **Metadata** (GPU lane). The title and copyright pages (the first 20 and the last 20 by default; a book knob, see below) are read from
   the text layer, or recognised by MinerU when there is none. Scripts come first: the PDF's own info
   (junk such as `single.dvi` or the file name is ignored), ISBN with its checksum, year, edition,
   volume, the language of the body text. With an ISBN the stand asks Open Library (English editions),
   Labirint (Russian editions, with series and translator) and Google Books (when a key is set);
   without one it searches Open Library, Labirint and Bookvoed by title and author, taking a value only
   when exactly one edition matches. Book cards (schema.org markup) are read from the sites the book
   names, the shop pages they link to, and book sites a local metasearch (SearXNG) returns; they fill
   the related editions, never the book's own ISBN. Only then a local model (ollama) reads the title
   pages for what is still missing and names the book's subject.
4. **Resolve.** Each field takes the value of its highest-ranked source. Sources that disagree are
   marked as a conflict and lower the confidence. A field nobody found stays empty and lists every
   source that was tried; nothing is guessed. The result is a new metadata version; older versions
   are kept.
5. **What you get.** `GET /v1/books/{id}` shows files, pages, text layer, bookmarks, printed contents
   and metadata; `GET /v1/books/{id}/metadata` shows every field with its value, source, confidence
   and attempts. A field can be set by hand (`PATCH /v1/books/{id}/metadata/{name}`, a new version);
   the book content itself is never edited by hand. `POST /v1/books/{id}/recollect` collects again.

Book-level knobs can be given at submission (`"knobs": {...}` in `POST /v1/books`) or changed later
(`PATCH /v1/books/{id}/knobs`): `metadata.title_pages.head` and `.tail` (20 and 20 by default, in
`config/metadata.yaml`) and `toc.contents_pages`, the printed contents pages as `[[first, last], ...]`
when you know where they are. A change takes effect at the next collection.

A stage that keeps failing stops after its attempt budget (3 to 5, per stage, in
`config/budgets.yaml`) and waits; after a look, `POST /v1/jobs/retry` gives it a fresh budget.

## Running the stand

The stand reuses what rag-lab has already downloaded: the converter images with their models, the
ollama models, the Hugging Face cache and the books on rag-lab's shelf. Nothing is pulled. Both
stands share one GPU, so rag-lab's converters must be down while ocr-lab's run.

```bash
cp .env.example .env                      # optional keys: a cloud model, Google Books
docker compose --profile convert up -d    # postgres, migrations, api, worker, ollama, converters
curl -s localhost:8100/v1/stand | jq      # health, engine builds, who holds the GPU, worker code
```

Submit a book and wait for it:

```bash
curl -s -XPOST localhost:8100/v1/books -H 'content-type: application/json' \
     -d '{"shelf_paths": ["kafka-the-definitive-guide-2e/kafka-the-definitive-guide-2e.pdf"]}'
curl -s 'localhost:8100/v1/jobs?type=intake'                    # the job id
curl -s 'localhost:8100/v1/jobs/<id>/wait?timeout=900'         # returns when it and its children finish
curl -s localhost:8100/v1/books/<book>/metadata
```

The same operations are MCP tools at `http://localhost:8100/mcp`: `add_book`, `books`, `book`,
`metadata`, `set_metadata`, `set_book_knobs`, `recollect`, `jobs`, `job`, `wait_job`, `retry_jobs`, `pause_jobs`,
`resume_jobs`, `cancel_jobs`, `queue`, `stand`.

## Layout

```text
app/
  server.py, mcp_tools.py     FastAPI with the MCP server mounted at /mcp
  api/v1/, use_cases/         REST routes and the use cases they share with MCP tools
  worker.py, job_queue.py     Postgres queue: a serial GPU lane and parallel CPU lanes
  job_handlers/, stages/      what each job runs: intake, metadata
  engines/                    converter supervisors, Docling and MinerU clients, GPU handover
  artifacts.py                atomic stage files with a manifest in Postgres
  models_client.py            OpenAI-compatible model calls, cached
config/                       attempt budgets, which model each step calls
db/migrations/, db/schema.sql dbmate migrations and the schema dump the tests load
diagrams/                     .drawio.svg pictures with their draw.io source inside
data/                         books, stage artifacts, bundles (a volume, not in git)
specs/                        spec, plan, data model, contracts, tasks
```

## Development

```bash
uv sync
scripts/check.sh          # ruff, then pytest (unit and door tests need postgres on localhost:5433)
uv run pytest -m stand    # checks against the running stand
scripts/dump_schema.sh    # after a new migration
```

Diagrams are `.drawio.svg` files: open them in draw.io (or its VS Code extension), edit, save; the
picture and its source stay in one file.
