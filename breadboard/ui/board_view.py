"""The breadboard canvas: drawing, scaling and the board tools (design.md §4)."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from ..board import RAILS, ROWS, Chip, Led, LogicInput, Part, PowerSupply, Resistor, Wire, parse_hole
from ..chips import CHIPS
from ..logic import Logic
from .geometry import CHANNEL_SLOT, NUMBER_SLOTS, ROW_SLOTS, BoardGeometry

if TYPE_CHECKING:
    from .app import App

BOARD_COLOUR = "#f7f3e9"
EMPTY_HOLE = "#d8d4ca"
VALUE_COLOURS = {Logic.ONE: "#dc2626", Logic.ZERO: "#2563eb", Logic.X: "#f59e0b", Logic.Z: "#9ca3af"}
LED_COLOURS = {Logic.ONE: "#ff3b30", Logic.ZERO: "#5c1f1f", Logic.X: "#f59e0b"}
LEG_COLOUR = "#6b7280"
SELECTED_INPUT, SELECTED_OUTPUT = "#7c3aed", "#059669"

TOOLS = {   # tool -> (label, shortcut, help text)
    "wire": ("Wire", "w", "Click two holes to connect them with a wire."),
    "chip": ("Chip", "c", "Click a column to place the chip there (pin 1 in row f)."),
    "input": ("Input", "i", "Click a hole to add a switch. Click a switch to flip it."),
    "led": ("LED", "l", "Click the anode (+) hole, then the cathode (−) hole."),
    "resistor": ("Resistor", "r", "Click the holes for the resistor's two legs."),
    "power": ("Power", "p", "Click the + hole, then the − hole."),
    "delete": ("Delete", "d", "Click a part to remove it."),
}
TWO_HOLE_TOOLS = {"wire": Wire, "led": Led, "resistor": Resistor, "power": PowerSupply}
CHIP_LABELS = {f"{key} {spec.gates[0][0].name}": key for key, spec in CHIPS.items()}
DRAW_LAYER = {Chip: 0, Wire: 1, Resistor: 1, Led: 2, LogicInput: 3, PowerSupply: 3}
BOARD_SIZES = {"Half (30)": 30, "Full (63)": 63}


class BoardView(ttk.Frame):
    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        self.tool = tk.StringVar(value="wire")
        self.chip = tk.StringVar(value=next(iter(CHIP_LABELS)))
        self.size = tk.StringVar(value="Half (30)")
        self.pending: str | None = None              # first hole of a two-hole part
        self.geometry: BoardGeometry | None = None
        self._job = None

        self.canvas = tk.Canvas(self, background="white", highlightthickness=0)
        xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        c = self.canvas
        c.bind("<Configure>", lambda _: self.schedule_redraw())
        c.bind("<Button-1>", self._on_click)
        c.bind("<Button-2>", self._on_right_click)
        c.bind("<Button-3>", self._on_right_click)
        c.bind("<Motion>", self._on_motion)
        c.bind("<Enter>", lambda _: c.focus_set())
        c.bind("<Escape>", lambda _: self.cancel())
        for tool, (_, key, _) in TOOLS.items():      # shortcuts on the canvas, not the window
            c.bind(f"<KeyPress-{key}>", lambda _, t=tool: self.tool.set(t))
        self.tool.trace_add("write", lambda *_: self.cancel())

    # ------------------------------------------------------------------ toolbar

    def toolbar(self, parent) -> ttk.Frame:
        bar = ttk.Frame(parent)
        for tool, (label, key, _) in TOOLS.items():
            ttk.Radiobutton(bar, text=label, value=tool, variable=self.tool, style="Toolbutton",
                            underline=label.lower().index(key)).pack(side="left", padx=1)
            if tool == "chip":
                ttk.Combobox(bar, textvariable=self.chip, values=list(CHIP_LABELS), state="readonly",
                             width=9).pack(side="left", padx=(0, 6))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        size = ttk.Combobox(bar, textvariable=self.size, values=list(BOARD_SIZES), state="readonly", width=9)
        size.pack(side="left")
        size.bind("<<ComboboxSelected>>", lambda _: self._resize())
        ttk.Button(bar, text="Clear board", command=self.app.clear_board).pack(side="left", padx=(8, 0))
        return bar

    def _resize(self) -> None:
        columns = BOARD_SIZES[self.size.get()]
        if not self.app.board_edit(lambda board: board.resize(columns)):
            self.sync_size()

    def sync_size(self) -> None:
        columns = self.app.board.columns
        self.size.set(next((k for k, v in BOARD_SIZES.items() if v == columns), f"{columns} columns"))

    # ------------------------------------------------------------------ actions

    def click(self, hole: str) -> None:
        """What a left click on a hole does, depending on the tool."""
        board = self.app.board
        tool = self.tool.get()
        part = board.part_at(hole)
        if tool == "delete":
            if part is not None:
                self.app.board_edit(lambda b: b.remove(part))
        elif isinstance(part, LogicInput) and self.pending is None:
            self.app.toggle_switch(part)
        elif isinstance(part, Chip) and self.pending is None:
            pin = next(int(p) for p, h in part.pins().items() if h == hole)
            self.app.select_board_pin(part, pin)
        elif tool == "chip":
            _, column = parse_hole(hole)
            spec = CHIPS[CHIP_LABELS[self.chip.get()]]
            self.app.board_edit(lambda b: b.place(Chip(spec, column)))
        elif tool == "input":
            self.app.board_edit(lambda b: b.place(LogicInput(hole)))
        elif self.pending is None:
            if part is not None:
                self.app.say(f"Hole {hole} is already in use.", error=True)
            else:
                self.pending = hole
                self.app.say(f"{TOOLS[tool][2]} First hole: {hole}.")
        else:
            first, self.pending = self.pending, None
            if first == hole:
                self.app.say("Pick two different holes.", error=True)
            elif self.app.board_edit(lambda b: b.place(TWO_HOLE_TOOLS[tool](first, hole))):
                self.app.say(TOOLS[tool][2])
        self.redraw()

    def remove_at(self, hole: str) -> None:
        part = self.app.board.part_at(hole)
        if part is not None:
            self.app.board_edit(lambda b: b.remove(part))

    def cancel(self) -> None:
        self.pending = None
        self.app.say(TOOLS[self.tool.get()][2])
        self.redraw()

    # ------------------------------------------------------------------ events

    def _event_hole(self, event) -> str | None:
        if self.geometry is None:
            return None
        return self.geometry.hole_at(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))

    def _on_click(self, event) -> None:
        self.canvas.focus_set()
        if (hole := self._event_hole(event)) is not None:
            self.click(hole)

    def _on_right_click(self, event) -> None:
        if (hole := self._event_hole(event)) is not None:
            self.remove_at(hole)

    def _on_motion(self, event) -> None:
        hole = self._event_hole(event)
        if hole is None:
            self.app.set_hover("")
            return
        board = self.app.board
        net = board.net_at(hole)
        text = f"{hole}: " + ("not connected" if net is None else f"net {net.name} = {net.value.value}"
                              + ("" if net.strong or net.value is Logic.Z else " (weak)"))
        part = board.part_at(hole)
        if isinstance(part, Chip):
            pin = next(int(p) for p, h in part.pins().items() if h == hole)
            text = f"{part.spec.name} pin {pin} ({part.spec.pin_names().get(pin, 'not used')}), {text}"
        self.app.set_hover(text)

    # ------------------------------------------------------------------ drawing

    def schedule_redraw(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after_idle(self.redraw)

    def _net_colour(self, hole: str) -> str:
        net = self.app.board.net_at(hole)
        return EMPTY_HOLE if net is None else VALUE_COLOURS[net.value]

    def redraw(self) -> None:
        self._job = None
        board = self.app.board
        width, height = max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)
        self.geometry = g = BoardGeometry(board.columns, width, height, min_pitch=self.winfo_fpixels("8p"))
        c = self.canvas
        c.delete("all")
        c.configure(scrollregion=(0, 0, max(width, g.left * 2 + g.board_width), max(height, g.top * 2 + g.board_height)))
        self._draw_board()
        for part in sorted(board.parts, key=lambda p: DRAW_LAYER[type(p)]):
            self._draw_part(part)
        for part in board.parts:                     # chip names last, so wires never hide them
            if isinstance(part, Chip):
                x0, _ = g.hole_xy(part.pin_hole(part.spec.pin_count))
                x1, _ = g.hole_xy(part.pin_hole(part.spec.pin_count // 2))
                c.create_text((x0 + x1) / 2, g.slot_y(CHANNEL_SLOT), text=part.spec.name, fill="white",
                              font=("TkDefaultFont", g.font(0.36), "bold"))
        self._draw_selection()
        if self.pending is not None:
            x, y = g.hole_xy(self.pending)
            r = g.size(0.4)
            c.create_oval(x - r, y - r, x + r, y + r, outline="#111", width=2, dash=(3, 2))

    def _draw_board(self) -> None:
        c, g, board = self.canvas, self.geometry, self.app.board
        left, right = g.column_x(0), g.column_x(board.columns + 1)
        top, bottom = g.slot_y(-1), g.slot_y(max(ROW_SLOTS.values()) + 1)
        c.create_rectangle(left, top, right, bottom, fill=BOARD_COLOUR, outline="#cfc8b8")
        channel = g.slot_y(CHANNEL_SLOT)
        c.create_rectangle(left, channel - g.size(0.17), right, channel + g.size(0.17), fill="#e6e0d2", outline="")
        small = ("TkDefaultFont", g.font(0.3))
        for rail in RAILS:                           # red line above + rails, blue line below - rails
            y = g.slot_y(ROW_SLOTS[rail])
            offset = g.pitch * 0.3 * (-1 if rail[1] == "+" else 1)
            c.create_line(left + g.pitch / 3, y + offset, right - g.pitch / 3, y + offset,
                          fill="#dc2626" if rail[1] == "+" else "#2563eb", width=g.size(0.06))
            c.create_text(left + g.pitch / 2, y, text=rail[1].replace("-", "−"), fill="#555", font=small)
        for column in range(1, board.columns + 1):
            if column == 1 or column % 5 == 0:
                for slot in NUMBER_SLOTS:
                    c.create_text(g.column_x(column), g.slot_y(slot), text=str(column), fill="#777", font=small)
        for row in ROWS:
            y = g.slot_y(ROW_SLOTS[row])
            c.create_text(left + g.pitch / 2, y, text=row, fill="#777", font=small)
            c.create_text(right - g.pitch / 2, y, text=row, fill="#777", font=small)
        r = g.size(0.21)
        for row in ROW_SLOTS:
            for column in range(1, board.columns + 1):
                hole = f"{row}{column}"
                x, y = g.hole_xy(hole)
                c.create_oval(x - r, y - r, x + r, y + r, fill=self._net_colour(hole), outline="")

    def _wire_colour(self, hole: str) -> str:
        net = self.app.board.net_at(hole)
        return "#15803d" if net is None else VALUE_COLOURS[net.value]

    def _draw_part(self, part: Part) -> None:
        c, g, board = self.canvas, self.geometry, self.app.board
        label_font = ("TkDefaultFont", g.font(0.38), "bold")
        if isinstance(part, Chip):
            self._draw_chip(part)
        elif isinstance(part, Wire):
            (xa, ya), (xb, yb) = g.hole_xy(part.a), g.hole_xy(part.b)
            length = math.hypot(xb - xa, yb - ya)
            bow = min(0.12 * length, 1.5 * g.pitch)  # a slight curve, so it doesn't cover holes in a row
            mx, my = (xa + xb) / 2 - (yb - ya) / length * bow, (ya + yb) / 2 + (xb - xa) / length * bow
            c.create_line(xa, ya, mx, my, xb, yb, smooth=True, fill=self._wire_colour(part.a),
                          width=g.size(0.17, 2), capstyle="round")
        elif isinstance(part, Resistor):
            (xa, ya), (xb, yb) = g.hole_xy(part.a), g.hole_xy(part.b)
            c.create_line(xa, ya, xb, yb, fill=LEG_COLOUR, width=g.size(0.08))
            c.create_line(xa + (xb - xa) * 0.3, ya + (yb - ya) * 0.3, xa + (xb - xa) * 0.7, ya + (yb - ya) * 0.7,
                          fill="#d4a373", width=g.size(0.38))
        elif isinstance(part, Led):
            (xa, ya), (xk, yk) = g.hole_xy(part.anode), g.hole_xy(part.cathode)
            c.create_line(xa, ya, xk, yk, fill=LEG_COLOUR, width=g.size(0.08))
            t = min(0.5, 0.6 * g.pitch / math.hypot(xk - xa, yk - ya))   # body near the anode end
            mx, my = xa + (xk - xa) * t, ya + (yk - ya) * t
            r = g.size(0.33)
            c.create_oval(mx - r, my - r, mx + r, my + r, outline="#333",
                          fill=LED_COLOURS.get(board.led(part), LED_COLOURS[Logic.ZERO]))
            c.create_text(xa - r, ya - r, text="+", font=("TkDefaultFont", g.font(0.33), "bold"))
            if part.label:
                self._label(mx + r * 1.4, my, part.label, "w", label_font)
        elif isinstance(part, LogicInput):
            x, y = g.hole_xy(part.hole)
            r = g.size(0.38)
            on = part.value is Logic.ONE
            c.create_rectangle(x - r, y - r, x + r, y + r, outline="#111", fill="#16a34a" if on else "#4b5563")
            c.create_text(x, y, text=part.value.value, fill="white", font=("TkDefaultFont", g.font(0.38), "bold"))
            if part.label:
                self._label(x - r * 1.3, y, part.label, "e", label_font)
        elif isinstance(part, PowerSupply):
            r = g.size(0.33)
            for hole, sign, colour in ((part.plus, "+", "#dc2626"), (part.minus, "−", "#111")):
                x, y = g.hole_xy(hole)
                c.create_oval(x - r, y - r, x + r, y + r, fill=colour, outline="")
                c.create_text(x, y, text=sign, fill="white", font=("TkDefaultFont", g.font(0.38), "bold"))
            x, y = g.hole_xy(part.plus)
            c.create_text(x, y - g.pitch * 0.7, text="5V", fill="#111", font=("TkDefaultFont", g.font(0.33), "bold"))

    def _label(self, x: float, y: float, text: str, anchor: str, font) -> None:
        """A part's name, on a light background so it stays readable over the holes."""
        c = self.canvas
        item = c.create_text(x, y, text=text, anchor=anchor, font=font)
        x0, y0, x1, y1 = c.bbox(item)
        c.tag_lower(c.create_rectangle(x0 - 2, y0, x1 + 2, y1, fill="#fffdf5", outline="#cfc8b8"), item)

    def _draw_chip(self, chip: Chip) -> None:
        c, g, spec = self.canvas, self.geometry, chip.spec
        x0, y_top = g.hole_xy(chip.pin_hole(spec.pin_count))
        x1, y_bottom = g.hole_xy(chip.pin_hole(spec.pin_count // 2))
        leg = g.size(0.17)
        for pin in range(1, spec.pin_count + 1):     # legs, coloured by their net's value
            x, y = g.hole_xy(chip.pin_hole(pin))
            c.create_rectangle(x - leg, y - leg, x + leg, y + leg, fill=self._net_colour(chip.pin_hole(pin)),
                               outline="#555")
        top, bottom = y_top + g.pitch * 0.35, y_bottom - g.pitch * 0.35
        c.create_rectangle(x0 - g.pitch * 0.45, top, x1 + g.pitch * 0.45, bottom, fill="#1f2937", outline="#111")
        mid, n = (top + bottom) / 2, g.size(0.25)
        c.create_arc(x0 - g.pitch * 0.45 - n, mid - n, x0 - g.pitch * 0.45 + n, mid + n,
                     start=-90, extent=180, fill=BOARD_COLOUR, outline="#111")       # notch
        d = g.size(0.12)
        c.create_oval(x0 - d, bottom - 3 * d, x0 + d, bottom - d, fill="#e5e7eb", outline="")   # pin 1 dot

    def _draw_selection(self) -> None:
        selected = self.app.selected_board_gate()
        if selected is None:
            return
        chip, index = selected
        if chip not in self.app.board.parts:
            return
        g = self.geometry
        _, inputs, output = chip.spec.gates[index]
        r = g.size(0.32)
        for pin, colour in [(p, SELECTED_INPUT) for p in inputs] + [(output, SELECTED_OUTPUT)]:
            x, y = g.hole_xy(chip.pin_hole(pin))
            self.canvas.create_rectangle(x - r, y - r, x + r, y + r, outline=colour, width=g.size(0.1, 2))
