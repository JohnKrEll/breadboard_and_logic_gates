"""Gate symbol outlines in symbol coordinates (grid units). No tkinter, so they can be tested.

ANSI distinctive shapes or IEC rectangles (design.md §7.3).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = tuple[float, float]

INVERTING = {"NAND", "NOR", "NOT"}
BASE = {"NAND": "AND", "NOR": "OR", "AND3": "AND", "NOT": "BUF"}
IEC_LABELS = {"AND": "&", "OR": "≥1", "XOR": "=1", "BUF": "1"}
BUBBLE_RADIUS = 0.22


@dataclass
class Outline:
    polygons: list[list[Point]]                       # filled body
    lines: list[list[Point]] = field(default_factory=list)   # extra strokes (XOR's back curve)
    bubble: Point | None = None                       # centre of the inverting bubble
    label: str = ""                                   # IEC: "&", "≥1", …
    body_right: float = 3.5                           # where the output lead starts
    body_left: float = 1.0                            # where the input leads end (under the body)


def bezier(p0: Point, p1: Point, p2: Point, n: int = 14) -> list[Point]:
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in (i / n for i in range(n + 1))]


def outline(gate: str, height: float, style: str = "ansi") -> Outline:
    """The body of a gate symbol `height` grid units tall (4 wide)."""
    m = height / 2
    inverted = gate in INVERTING
    base = BASE.get(gate, gate)
    if style == "iec":
        return Outline([[(0.6, 0), (3.4, 0), (3.4, height), (0.6, height)]],
                       bubble=(3.4 + BUBBLE_RADIUS, m) if inverted else None,
                       label=IEC_LABELS[base], body_right=3.4 + (2 * BUBBLE_RADIUS if inverted else 0),
                       body_left=0.6)
    if base == "AND":
        arc = [(1.6 + 1.9 * math.cos(a), m + m * math.sin(a))
               for a in (math.radians(d) for d in range(-90, 91, 10))]
        return Outline([[(0.5, 0)] + arc + [(0.5, height)]],
                       bubble=(3.5 + BUBBLE_RADIUS, m) if inverted else None,
                       body_right=3.5 + (2 * BUBBLE_RADIUS if inverted else 0), body_left=0.5)
    if base in ("OR", "XOR"):
        dx = 0.35 if base == "XOR" else 0
        back = bezier((0.4 + dx, height), (1.2 + dx, m), (0.4 + dx, 0))
        shape = bezier((0.4 + dx, 0), (2.4, 0), (3.5, m)) + bezier((3.5, m), (2.4, height), (0.4 + dx, height)) + back
        lines = [bezier((0.4, height), (1.2, m), (0.4, 0))] if base == "XOR" else []
        return Outline([shape], lines, bubble=(3.5 + BUBBLE_RADIUS, m) if inverted else None,
                       body_right=3.5 + (2 * BUBBLE_RADIUS if inverted else 0), body_left=1.0)
    if base == "BUF":
        return Outline([[(0.6, m - 1), (3.2, m), (0.6, m + 1)]],
                       bubble=(3.2 + BUBBLE_RADIUS, m) if inverted else None,
                       body_right=3.2 + (2 * BUBBLE_RADIUS if inverted else 0), body_left=0.6)
    raise ValueError(f"no symbol for {gate}")
