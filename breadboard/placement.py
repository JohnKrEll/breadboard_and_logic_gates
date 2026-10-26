"""Automatic placement of schematic symbols: layered, left to right (design.md §7.4)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schematic import Schematic

COLUMN_GAP = 3        # grid units between columns, plus one per net leaving the column
ROW_GAP = 3           # grid units from one symbol's bottom edge to the next one's top


def auto_place(sch: Schematic, fixed: frozenset[str] = frozenset()) -> None:
    """Inputs on the left, outputs on the right, columns by longest path.
    Symbols in `fixed` keep their positions."""
    preds: dict[str, list[str]] = {id: [] for id in sch.symbols}
    for inp, out in sch.sources.items():
        preds[inp.symbol].append(out.symbol)
    succs: dict[str, list[str]] = {id: [] for id in sch.symbols}
    for id, ps in preds.items():
        for p in ps:
            succs[p].append(id)

    # 1. feedback: edges back to a symbol still on the search path are ignored for levels
    back: set[tuple[str, str]] = set()
    state: dict[str, int] = {}
    order: list[str] = []

    def visit(id: str) -> None:
        stack = [(id, iter(succs[id]))]               # iterative: big circuits nest deeply
        state[id] = 1
        while stack:
            node, children = stack[-1]
            for nxt in children:
                if state.get(nxt) == 1:
                    back.add((node, nxt))
                elif nxt not in state:
                    state[nxt] = 1
                    stack.append((nxt, iter(succs[nxt])))
                    break
            else:
                stack.pop()
                state[node] = 2
                order.append(node)

    starts = [s.id for s in sch.symbols.values() if s.kind in ("input", "const")]
    for id in starts + list(sch.symbols):
        if id not in state:
            visit(id)
    order.reverse()                                     # a topological order without back edges

    # 2. columns by longest path from the inputs; all outputs in the last column
    level: dict[str, int] = {}
    for id in order:
        forward = [p for p in preds[id] if (p, id) not in back]
        if sch.symbols[id].kind in ("input", "const"):
            level[id] = 0
        else:
            level[id] = 1 + max((level[p] for p in forward), default=0)
    last = max((level[id] for id, s in sch.symbols.items() if s.kind != "output"), default=0) + 1
    for id, s in sch.symbols.items():
        if s.kind == "output":
            level[id] = last

    columns: dict[int, list[str]] = {}
    for id in sch.symbols:
        columns.setdefault(level[id], []).append(id)

    # 3. order each column by the average position of its sources (barycentre)
    rank: dict[str, float] = {}
    for k in sorted(columns):
        if k > 0:
            def barycentre(id: str) -> float:
                ps = [rank[p] for p in preds[id] if p in rank]
                return sum(ps) / len(ps) if ps else float("inf")
            columns[k].sort(key=barycentre)
        for i, id in enumerate(columns[k]):
            rank[id] = i

    # 4. x: as wide as the widest symbol, plus a gap that grows with the nets leaving the column
    x = 0
    for k in sorted(columns):
        leaving = {o for o in sch.sources.values() if o.symbol in columns[k]}
        for id in columns[k]:
            if id not in fixed:
                sch.symbols[id].x = x
        x += max(sch.symbols[id].size()[0] for id in columns[k]) + COLUMN_GAP + len(leaving)

    # 5. y: line each symbol's inputs up with its sources, keeping the order and the spacing
    pending = {id for id in sch.symbols if id not in fixed}
    for k in sorted(columns):
        bottom = None
        for id in columns[k]:
            s = sch.symbols[id]
            if id in fixed:
                bottom = max(bottom or 0, s.y + s.size()[1] + ROW_GAP)
                continue
            ys = [sch.port_xy(out)[1] - s.pin_offset(inp.pin)[1]
                  for inp, out in sch.sources.items() if inp.symbol == id and level[out.symbol] < k]
            ideal = round(sum(ys) / len(ys)) if ys else 0
            s.y = ideal if bottom is None else max(ideal, bottom)
            pending.discard(id)
            while fixed and not sch.fits(id, s.x, s.y, ignore=frozenset(pending)):
                s.y += 1                                # don't land on a symbol the user placed
            bottom = s.y + s.size()[1] + ROW_GAP
