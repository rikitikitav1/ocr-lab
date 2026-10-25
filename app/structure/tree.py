# a book's structure as a tree: each node's parent is the nearest node before it on a higher level
def parents(levels: list[int]) -> list[int | None]:
    out, open_nodes = [], []
    for i, level in enumerate(levels):
        while open_nodes and levels[open_nodes[-1]] >= level:
            open_nodes.pop()
        out.append(open_nodes[-1] if open_nodes else None)
        open_nodes.append(i)
    return out


def depth(levels: list[int]) -> int:
    return max(levels, default=0)


# no shape signal for a deeper level is found yet, so every book reads its top nodes
def reading_level(levels: list[int]) -> int:
    return 0
