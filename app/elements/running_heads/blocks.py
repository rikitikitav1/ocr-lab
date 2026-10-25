# the running head element in the blocks: the slot lines a page layout claims, marked and dropped
from document.model import Caption, Heading, ListBlock, PageMarker, Paragraph

from elements import folding


# a block whose whole text is a slot line its page layout claims, or its page's claimed lines run together, is marked
def mark_slots(blocks: list, slots: dict[int, list[tuple[str, str, float]]],
               parts: bool = False) -> tuple[list, int]:
    out, n, here = [], 0, {}
    for b in blocks:
        if isinstance(b, PageMarker):
            lines = slots.get(b.file_page, [])
            here = {folding.fold(t): r for t, r, *_ in lines}
            if len(lines) > 1:
                here.setdefault(folding.fold(" ".join(t for t, *_ in lines)), lines[0][1])
        elif here and isinstance(b, (Heading, Paragraph, Caption)) and folding.fold(b.text) in here:
            b = b.model_copy(update={"slot": here[folding.fold(b.text)]})
            n += 1
        elif here and isinstance(b, ListBlock) and any(folding.fold(i.text) in here for i in b.items):
            items = [i.model_copy(update={"slot": here[folding.fold(i.text)]}) if folding.fold(i.text) in here else i
                     for i in b.items]
            n += sum(i.slot is not None for i in items)
            b = b.model_copy(update={"items": items})
        out.append(b)
    if parts:
        out, more = _mark_parts(out, slots)
        n += more
    return out, n


SLOT_BAND = 0.04


# blocks of one page standing in a claimed line's band whose words, together, are that line word for word
def _mark_parts(blocks: list, slots: dict[int, list[tuple[str, str, float]]]) -> tuple[list, int]:
    out, n, page = list(blocks), 0, None
    by_page: dict[int, list[int]] = {}
    for k, b in enumerate(out):
        if isinstance(b, PageMarker):
            page = b.file_page
        elif page is not None and isinstance(b, (Heading, Paragraph, Caption)) and not b.slot and b.where:
            by_page.setdefault(page, []).append(k)
    for page, ks in by_page.items():
        for text, reason, top in slots.get(page, []):
            words = folding.fold(text).split()
            near = [k for k in ks if not out[k].slot and abs(out[k].where.box[1] - top) <= SLOT_BAND]
            spans = [(k, folding.span(words, folding.fold(out[k].text).split())) for k in near]
            spans = [(k, s) for k, s in spans if s is not None and s[1] - s[0] < len(words)]
            covered = sorted(s for _, s in spans)
            if len(covered) < 2 or covered[0][0] != 0 or covered[-1][1] != len(words) or \
                    any(a[1] != b[0] for a, b in zip(covered, covered[1:], strict=False)):
                continue
            for k, _ in spans:
                out[k] = out[k].model_copy(update={"slot": reason})
                n += 1
    return out, n


# marked blocks go, but a heading a node opens at stays: a chapter's title is often its own running head
def drop_slots(blocks: list) -> tuple[list, int]:
    out, n = [], 0
    for b in blocks:
        if getattr(b, "slot", None) and not (isinstance(b, Heading) and b.node is not None):
            n += 1
            continue
        if isinstance(b, ListBlock) and any(i.slot for i in b.items):
            items = [i for i in b.items if not i.slot]
            n += len(b.items) - len(items)
            if not items:
                continue
            b = b.model_copy(update={"items": items})
        out.append(b)
    return out, n
