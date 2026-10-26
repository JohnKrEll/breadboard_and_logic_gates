"""Breadboard geometry that scales with the canvas. No tkinter, so it can be tested (design.md §4.2)."""
from __future__ import annotations

from ..board import parse_hole

# Vertical slot of each row. The missing slots are the gaps by the rails and the channel.
ROW_SLOTS = {"T+": 0, "T-": 1,
             "a": 3, "b": 4, "c": 5, "d": 6, "e": 7,
             "f": 9, "g": 10, "h": 11, "i": 12, "j": 13,
             "B+": 15, "B-": 16}
SLOT_ROWS = {slot: row for row, slot in ROW_SLOTS.items()}
CHANNEL_SLOT = 8
NUMBER_SLOTS = (2, 14)              # where the column numbers go


class BoardGeometry:
    def __init__(self, columns: int, width: float, height: float, min_pitch: float = 10.0):
        self.columns = columns
        span_x = columns + 1                             # one pitch of board edge on each side
        span_y = max(ROW_SLOTS.values()) + 2
        self.pitch = max(min_pitch, min(width / span_x, height / span_y))
        self.board_width, self.board_height = span_x * self.pitch, span_y * self.pitch
        self.left = max(0.0, (width - self.board_width) / 2)   # centred when it fits
        self.top = max(0.0, (height - self.board_height) / 2)

    def column_x(self, column: float) -> float:
        return self.left + column * self.pitch

    def slot_y(self, slot: float) -> float:
        return self.top + (slot + 1) * self.pitch

    def hole_xy(self, hole: str) -> tuple[float, float]:
        row, column = parse_hole(hole)
        return self.column_x(column), self.slot_y(ROW_SLOTS[row])

    def hole_at(self, x: float, y: float) -> str | None:
        column = round((x - self.left) / self.pitch)
        row = SLOT_ROWS.get(round((y - self.top) / self.pitch) - 1)
        if row is None or not 1 <= column <= self.columns:
            return None
        hx, hy = self.hole_xy(f"{row}{column}")
        if (x - hx) ** 2 + (y - hy) ** 2 > (self.pitch / 2) ** 2:
            return None                                  # between holes
        return f"{row}{column}"

    def size(self, fraction: float, minimum: float = 1.0) -> float:
        """Drawing sizes are fractions of the pitch, so everything scales together."""
        return max(minimum, fraction * self.pitch)

    def font(self, fraction: float = 0.33) -> int:
        """A canvas font size in pixels (negative, as tkinter wants it)."""
        return -max(6, round(fraction * self.pitch))
