# Quickstart: validating the feature end to end

Run guide, not an implementation. Routes and fields: `contracts/http_api.md`,
`contracts/bundle.md`; tables: `data-model.md`.

## Prerequisites

- rag-lab stack down (`docker compose --profile '*' down` in `../rag-lab`): both stands share the GPU.
- Local images `rag-lab-converter-docling` and `rag-lab-converter-mineru` present
  (`docker images | grep rag-lab-converter`); their models are baked into the images.
- `../rag-lab/datasets/inbox/books` present (the shelf).
- `.env` from `.env.example` with the model provider URL and key (ollama needs none).

## 1. Stand up (User Story 0, SC-009)

```bash
docker compose up -d
curl -s localhost:8100/v1/stand | jq
```

Expect: postgres, dbmate, api, worker healthy; both converters report a build stamp; no image pull
in the compose output.

## 2. Catalogue three books (User Story 0, SC-010)

```bash
for p in kafka-the-definitive-guide-2e/kafka-the-definitive-guide-2e.pdf \
         unix-4-3bsd-reference/<file>.pdf \
         think-python-2e/think-python-2e.pdf; do
  curl -s -XPOST localhost:8100/v1/books -H 'content-type: application/json' \
       -d "{\"shelf_paths\": [\"$p\"]}" | jq '.id, .stage'
done
curl -s localhost:8100/v1/books/1/metadata | jq
```

Expect: every field filled with source and confidence, or null with every source listed in
`attempts`; the scan shows pages without a text layer; resubmitting a file returns the same id.

## 3. Convert one book (User Story 1, 3)

```bash
curl -s -XPOST localhost:8100/v1/books/1/runs -d '{"format": "markdown"}' \
     -H 'content-type: application/json' | jq '.run.id, .job.id'
curl -s 'localhost:8100/v1/jobs/<job>/wait?timeout=3600' | jq '.finished'
curl -s localhost:8100/v1/runs/<run>/report | jq '.numbers, .images'
```

Expect: bundle under `data/bundles/1/<run>/` with `.md`, `images/`, `profile.yaml`, `report.json`;
`numbers.pieces_done` equal to `numbers.pieces`; `images.broken_links == 0`; every value in
`profile.yaml` carries a source and evidence.

## 4. Move the bundle (SC-004)

```bash
cp -r data/bundles/1/<run> /tmp/moved && python scripts/check_links.py /tmp/moved
```

Expect: zero broken links, zero unreferenced images.

## 5. Kill and resume (User Story 2, SC-005)

Start a run on a long book, wait until `GET /runs/<id>/nodes` shows some nodes done, then
`docker compose kill worker && docker compose up -d worker`, then
`POST /runs/<id>/resume`. Expect: done pieces keep their artifacts (same sha), only the
interrupted piece reruns, and the final bundle is byte-identical to an uninterrupted run of the
same book and profile (test `tests/stand/test_kill_resume.py`).

## 6. Rerun one node (User Story 1, scenario 6)

```bash
curl -s -XPOST localhost:8100/v1/runs/<run>/nodes/4/rerun \
     -d '{"overrides": {"blocks.sidebars": "blockquote"}}' -H 'content-type: application/json'
```

Expect: only the artifacts of the piece holding node 4 are new; book metrics recomputed; the answer names
`nodes_rerun`, and the report shows the override under `profile.piece_overrides`.

## 7. Evaluation with a gate (User Story 4)

Create a set from the first evaluation books (`research.md` R15), register a gate, run a baseline,
change one shared option, run again. Expect: `GET /eval/runs/<id>` lists each worse member with
reasons and counts members whose output changed although the change did not fire.

## 8. Gate for the repo

```bash
scripts/check.sh   # ruff, then pytest -n 8
```
