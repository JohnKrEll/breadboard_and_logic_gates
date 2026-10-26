"""Wire routing for schematics: A* on the grid, with rip-up and reroute (design.md §7.5)."""
from __future__ import annotations

import heapq
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .schematic import Port

if TYPE_CHECKING:
    from .schematic import Schematic

STEP, BEND, CROSS = 1, 2, 3             # costs
RIGHT = (1, 0)
Cell = tuple[int, int]


@dataclass
class RoutedWire:
    source: Port
    target: Port
    points: list[Cell]                  # corners, from the branch point to the target port
    routed: bool = True                 # False: no path found, drawn as a straight dashed line


def route_once(sch: Schematic, first: list[Port]) -> tuple[list[RoutedWire], list[Cell]]:
    """Route every net, the ones in `first` first. Wires go around symbols, never overlap
    another net, may cross one at a right angle, and branch off their own net's tree."""
    if not sch.symbols:
        return [], []
    blocked: set[Cell] = set()
    for s in sch.symbols.values():
        w, h = s.size()
        blocked |= {(x, y) for x in range(s.x, s.x + w + 1) for y in range(s.y, s.y + h + 1)}
    x0, y0, x1, y1 = sch.bounds()
    x0, y0, x1, y1 = x0 - 3, y0 - 3, x1 + 3, y1 + 3
    used: dict[Cell, dict[Port, set[str]]] = {}        # cell -> net -> {"h", "v"}
    nets = sch.nets()
    wires: list[RoutedWire] = []
    edges: dict[Port, set[frozenset]] = {}

    # the cell in front of every port belongs to that port's net (None: kept free)
    reserved: dict[Cell, Port | None] = {}
    for s in sch.symbols.values():
        for pin in s.input_pins():
            x, y = sch.port_xy(Port(s.id, pin))
            reserved[(x - 1, y)] = sch.sources.get(Port(s.id, pin))
        if s.has_output():
            x, y = sch.port_xy(Port(s.id, "out"))
            reserved[(x + 1, y)] = Port(s.id, "out")

    def orient(d: Cell) -> str:
        return "h" if d[1] == 0 else "v"

    for src in first + sorted((n for n in nets if n not in first), key=sch.port_xy):
        sx, sy = sch.port_xy(src)
        tree = {(sx, sy)}
        edges[src] = set()
        for target in sorted(nets[src], key=lambda t: abs(sch.port_xy(t)[0] - sx) + abs(sch.port_xy(t)[1] - sy)):
            port = sch.port_xy(target)
            h = lambda c: abs(c[0] - port[0]) + abs(c[1] - port[1])
            heap, best, came = [], {}, {}
            for cell in tree:                          # a branch may start anywhere on the tree
                if any(n != src for n in used.get(cell, {})):
                    continue                            # but not where another net crosses
                d = RIGHT if cell == (sx, sy) else None
                best[(cell, d)] = 0
                heapq.heappush(heap, (h(cell), 0, cell, d))
            found = None
            while heap:
                _, cost, cell, d = heapq.heappop(heap)
                if cost > best.get((cell, d), 1e9):
                    continue
                if cell == port:
                    found = (cell, d)
                    break
                crossing = any(n != src for n in used.get(cell, {}))
                for step in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if cell == (sx, sy) and step != RIGHT:
                        continue                        # leave an output to the right
                    if d is not None and step == (-d[0], -d[1]):
                        continue                        # never turn back
                    if crossing and d is not None and step != d:
                        continue                        # no turning on another net's wire
                    nxt = (cell[0] + step[0], cell[1] + step[1])
                    if nxt == port:
                        if step != RIGHT:
                            continue                    # enter an input from the left
                        extra = 0
                    else:
                        if not (x0 <= nxt[0] <= x1 and y0 <= nxt[1] <= y1) or nxt in blocked or nxt in tree:
                            continue
                        if nxt in reserved and reserved[nxt] != src:
                            continue                    # in front of another net's port
                        there = [o for n, o in used.get(nxt, {}).items() if n != src]
                        if any(orient(step) in o or len(o) == 2 for o in there):
                            continue                    # overlap, or at another net's corner
                        extra = CROSS if there else 0
                    new = cost + STEP + extra + (BEND if d is not None and d != step else 0)
                    if new < best.get((nxt, step), 1e9):
                        best[(nxt, step)] = new
                        came[(nxt, step)] = (cell, d)
                        heapq.heappush(heap, (new + h(nxt), new, nxt, step))
            if found is None:
                wires.append(RoutedWire(src, target, [(sx, sy), port], routed=False))
                continue
            path, state = [], found
            while state in came:
                path.append(state[0])
                state = came[state]
            path.append(state[0])
            path.reverse()
            for a, b in zip(path, path[1:]):
                o = "h" if a[1] == b[1] else "v"
                for cell in (a, b):
                    used.setdefault(cell, {}).setdefault(src, set()).add(o)
                edges[src].add(frozenset((a, b)))
            tree |= set(path)
            corners = [p for i, p in enumerate(path) if i in (0, len(path) - 1)
                       or (path[i - 1][0] == p[0]) != (p[0] == path[i + 1][0])]
            wires.append(RoutedWire(src, target, corners))
    junctions = []
    for net_edges in edges.values():
        degree = Counter(cell for e in net_edges for cell in e)
        junctions += [cell for cell, n in degree.items() if n >= 3]
    return wires, junctions


def route(sch: Schematic, rounds: int = 4) -> tuple[list[RoutedWire], list[Cell]]:
    """Rip up and reroute: nets that failed go first in the next round. Keeps the best round."""
    first: list[Port] = []
    best = None
    for _ in range(rounds):
        wires, junctions = route_once(sch, first)
        failed = [w.source for w in wires if not w.routed]
        if best is None or len(failed) < best[0]:
            best = (len(failed), wires, junctions)
        if not failed:
            break
        first = list(dict.fromkeys(failed + first))
    return best[1], best[2]
