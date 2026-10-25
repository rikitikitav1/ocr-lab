# a byte-identity gate over finished runs: each reassembled fresh into a record, two records compared piece by piece


# a reassemble job's result as the record keeps it: lists, and per piece the text, images and counts
def entry(job_id: int, result: dict) -> dict:
    return {"run": result["run_id"], "job": job_id, "lists": result["book_lists"], "not_kept": result["not_kept"],
            "kept_text_changed": result["kept_text_changed"], "kept_numbers_changed": result["kept_numbers_changed"],
            "pieces": {str(p["ord"]): {"text_sha": p["text_sha"], "images_sha": p["images_sha"], "counts": p["after"]}
                       for p in result["pieces"]}}


# a book moves on its lists, a piece's text or images, a piece only one side has, or a count not named in ignore
def compare(base: dict, new: dict, ignore: tuple[str, ...] = ()) -> tuple[int, list[str]]:
    moved, lines = 0, []
    for book in sorted(base.keys() | new.keys(), key=int):
        a, b = base.get(book), new.get(book)
        if a is None or b is None:
            lines.append(f"{book} only in {'the base' if b is None else 'the new record'}")
            moved += 1
            continue
        lists = sorted(k for k in a["lists"].keys() | b["lists"].keys() if a["lists"].get(k) != b["lists"].get(k))
        text = [o for o in a["pieces"] if o in b["pieces"] and a["pieces"][o]["text_sha"] != b["pieces"][o]["text_sha"]]
        images = [o for o in a["pieces"] if o in b["pieces"]
                  and a["pieces"][o]["images_sha"] != b["pieces"][o]["images_sha"]]
        pieces = sorted(a["pieces"].keys() ^ b["pieces"].keys(), key=int)
        counts: dict[str, int] = {}
        for o in a["pieces"].keys() & b["pieces"].keys():
            x, y = a["pieces"][o]["counts"], b["pieces"][o]["counts"]
            for k in (x.keys() | y.keys()) - set(ignore):
                if x.get(k, "absent") != y.get(k, "absent"):
                    counts[k] = counts.get(k, 0) + 1
        if lists or text or images or pieces or counts:
            moved += 1
            found = {"lists": lists, "text": sorted(text, key=int)[:20], "texts": len(text),
                     "images": sorted(images, key=int)[:20], "pieces_apart": pieces, "counts": counts}
            lines.append(f"{book} {found}")
    lines.append(f"books moved: {moved} of {len(base.keys() | new.keys())}")
    return moved, lines
