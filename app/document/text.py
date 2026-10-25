# a block's words: its text whatever its kind, the words in it, how much two word counts share
import re
from collections import Counter

from document.model import Code, Contents, Formula, ListBlock, Table

# Chinese, Japanese and Korean write no spaces between words, so each of their characters counts as a word
CJK = "\u3040-\u30ff\u3130-\u318f\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff"
WORD = re.compile(rf"[{CJK}]|(?:(?![{CJK}])\w)+")


def block_text(block) -> str:
    match block:
        case Code():
            return block.text
        case Formula():
            return block.latex
        case Table():
            return " ".join(c.text for row in block.rows for c in row)
        case ListBlock():
            return " ".join(i.text + " " + " ".join(block_text(c) for c in i.children) for i in block.items)
        case Contents():
            return " ".join(block.entries)
    return getattr(block, "text", "")


def f1(a: Counter, b: Counter) -> float:
    common = sum((a & b).values())
    if not common:
        return 0.0
    precision, recall = common / sum(b.values()), common / sum(a.values())
    return 2 * precision * recall / (precision + recall)
