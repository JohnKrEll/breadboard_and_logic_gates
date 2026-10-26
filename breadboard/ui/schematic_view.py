"""The schematic canvas: gate symbols, wires, zoom and pan, and editing (design.md §7.3, §7.8)."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import simpledialog, ttk
from typing import TYPE_CHECKING

from ..logic import GATES, Logic
from ..routing import RoutedWire, route
from ..schematic import Port, Schematic, Symbol
from .board_view import VALUE_COLOURS
from .symbols import outline

if TYPE_CHECKING:
    from .app import App

LAMP_COLOURS = {Logic.ONE: "#ff3b30", Logic.ZERO: "#5c1f1f"}
SELECTION = "#7c3aed"
GATE_TOOLS = ["AND", "OR", "NAND", "NOR", "XOR", "NOT"]
TOOLS = {   # tool -> (label, shortcut, help text)
    "select": ("Select", "s", "Drag from a port to a port to wire them. Drag symbols to move them. "
                              "Click a switch to flip it, double-click a name to rename it."),
    "input": ("In", "i", "Click to place an input (a switch)."),
    "output": ("Out", "o", "Click to place an output (a lamp)."),
    "const0": ("0", None, "Click to place a constant 0."),
    "const1": ("1", None, "Click to place a constant 1."),
    **{name: (name, str(i), f"Click to place a {name} gate.") for i, name in enumerate(GATE_TOOLS, start=1)},
}
STYLES = {"ANSI": "ansi", "IEC": "iec"}


class SchematicView(ttk.Frame):
    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        self.tool = tk.StringVar(value="select")
        self.style = tk.StringVar(value="ANSI")
        self.zoom = 22.0                     # pixels per grid unit
        self.ox = self.oy = 40.0             # canvas position of grid point (0, 0)
        self.selection: set[str] = set()
        self.drag: dict | None = None
        self.routes: tuple[list[RoutedWire], list] | None = None
        self.hover_net: Port | None = None
        self._job = None

        self.canvas = c = tk.Canvas(self, background="white", highlightthickness=0)
        c.pack(fill="both", expand=True)
        c.bind("<Configure>", lambda _: self.schedule_redraw())
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._drag_to)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._double)
        c.bind("<ButtonPress-2>", self._pan_start)
        c.bind("<B2-Motion>", self._pan_to)
        c.bind("<Button-3>", self._right)
        c.bind("<Motion>", self._motion)
        c.bind("<Enter>", lambda _: c.focus_set())
        c.bind("<Button-4>", lambda e: self._wheel(e, 1))                # X11 wheel; Ctrl/Shift checked inside
        c.bind("<Button-5>", lambda e: self._wheel(e, -1))
        c.bind("<MouseWheel>", lambda e: self._wheel(e, 1 if e.delta > 0 else -1))
        for tool, (_, key, _) in TOOLS.items():      # shortcuts on the canvas, not the window
            if key:
                c.bind(f"<KeyPress-{key}>", lambda _, t=tool: self.tool.set(t))
        c.bind("<KeyPress-f>", lambda _: self.fit())
        c.bind("<Delete>", lambda _: self.delete_selection())
        c.bind("<BackSpace>", lambda _: self.delete_selection())
        c.bind("<Escape>", lambda _: self._escape())
        c.bind("<Control-a>", lambda _: self._select_all())
        for key, (dx, dy) in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1))):
            c.bind(f"<{key}>", lambda _, d=(dx, dy): self.nudge(*d))
        self.tool.trace_add("write", lambda *_: self.app.say(TOOLS[self.tool.get()][2]))

    # ------------------------------------------------------------------ toolbar

    def toolbar(self, parent) -> ttk.Frame:
        bar = ttk.Frame(parent)
        for tool, (label, key, _) in TOOLS.items():
            if tool == "AND":
                ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
            ttk.Radiobutton(bar, text=label, value=tool, variable=self.tool, style="Toolbutton").pack(side="left", padx=1)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        style = ttk.Combobox(bar, textvariable=self.style, values=list(STYLES), state="readonly", width=5)
        style.pack(side="left")
        style.bind("<<ComboboxSelected>>", lambda _: self.redraw())
        ttk.Button(bar, text="Fit", width=4, command=self.fit).pack(side="left", padx=(8, 0))
        return bar

    # ------------------------------------------------------------------ coordinates

    @property
    def sch(self) -> Schematic:
        return self.app.schematic

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return self.ox + x * self.zoom, self.oy + y * self.zoom

    def to_grid(self, event) -> tuple[float, float]:
        return ((self.canvas.canvasx(event.x) - self.ox) / self.zoom,
                (self.canvas.canvasy(event.y) - self.oy) / self.zoom)

    def fit(self) -> None:
        width, height = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        if not self.sch.symbols:
            self.zoom, self.ox, self.oy = 22.0, 40.0, 40.0
        else:
            x0, y0, x1, y1 = self.sch.bounds()
            x0, x1, y0, y1 = x0 - 4, x1 + 5, y0 - 2, y1 + 3      # room for names and wires
            self.zoom = max(6.0, min(60.0, width / (x1 - x0), height / (y1 - y0)))
            self.ox = width / 2 - (x0 + x1) / 2 * self.zoom
            self.oy = height / 2 - (y0 + y1) / 2 * self.zoom
        self.redraw()

    def invalidate(self) -> None:
        """The schematic changed: wires must be routed again."""
        self.routes = None
        self.selection &= set(self.sch.symbols)

    # ------------------------------------------------------------------ hit testing

    def port_at(self, gx: float, gy: float) -> Port | None:
        best, best_d = None, 0.6
        for s in self.sch.symbols.values():
            for port in self.sch.ports(s):
                px, py = self.sch.port_xy(port)
                d = math.hypot(px - gx, py - gy)
                if d < best_d:
                    best, best_d = port, d
        return best

    def symbol_at(self, gx: float, gy: float) -> Symbol | None:
        for s in self.sch.symbols.values():
            w, h = s.size()
            if s.x + 0.3 <= gx <= s.x + w - 0.3 and s.y - 0.2 <= gy <= s.y + h + 0.2:
                return s
        return None

    def name_at(self, gx: float, gy: float) -> Symbol | None:
        for s in self.sch.symbols.values():
            if s.kind not in ("input", "output") or not s.y <= gy <= s.y + 2:
                continue
            width = 0.6 * len(s.name) + 0.5
            if s.kind == "input" and s.x - width <= gx <= s.x + 0.3:
                return s
            if s.kind == "output" and s.x + 2.3 <= gx <= s.x + 2.5 + width:
                return s
        return None

    def wire_at(self, gx: float, gy: float) -> RoutedWire | None:
        for w in self.routed()[0]:
            for (ax, ay), (bx, by) in zip(w.points, w.points[1:]):
                if ax == bx and min(ay, by) - 0.3 <= gy <= max(ay, by) + 0.3 and abs(gx - ax) < 0.35:
                    return w
                if ay == by and min(ax, bx) - 0.3 <= gx <= max(ax, bx) + 0.3 and abs(gy - ay) < 0.35:
                    return w
        return None

    def routed(self) -> tuple[list[RoutedWire], list]:
        if self.routes is None:
            self.routes = route(self.sch)
        return self.routes

    def unrouted(self) -> list[RoutedWire]:
        return [w for w in self.routed()[0] if not w.routed]

    # ------------------------------------------------------------------ mouse

    def _press(self, event) -> None:
        self.canvas.focus_set()
        gx, gy = self.to_grid(event)
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        port = self.port_at(gx, gy)
        symbol = self.symbol_at(gx, gy)
        if port is not None:
            self.drag = {"kind": "wire", "port": port, "at": (cx, cy)}
        elif symbol is not None:
            if symbol.id not in self.selection:
                self.selection = (self.selection | {symbol.id}) if event.state & 0x1 else {symbol.id}
            self.drag = {"kind": "move", "start": (gx, gy), "d": (0, 0), "symbol": symbol.id,
                         "ids": set(self.selection)}
        elif (wire := self.wire_at(gx, gy)) is not None:
            self.drag = {"kind": "wire", "port": wire.source, "at": (cx, cy)}       # branch off this net
        elif self.tool.get() != "select":
            self.place(gx, gy)
        else:
            self.drag = {"kind": "band", "start": (cx, cy), "at": (cx, cy)}
        self.redraw()

    def _drag_to(self, event) -> None:
        if self.drag is None:
            return
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if self.drag["kind"] == "move":
            gx, gy = self.to_grid(event)
            sx, sy = self.drag["start"]
            self.drag["d"] = (round(gx - sx), round(gy - sy))
        else:
            self.drag["at"] = (cx, cy)
        self.redraw()

    def _release(self, event) -> None:
        drag, self.drag = self.drag, None
        if drag is None:
            return
        gx, gy = self.to_grid(event)
        if drag["kind"] == "wire":
            target = self.port_at(gx, gy)
            if target is not None and target != drag["port"]:
                self.connect(drag["port"], target)
        elif drag["kind"] == "move":
            dx, dy = drag["d"]
            if (dx, dy) != (0, 0):
                self.move(drag["ids"], dx, dy)
            else:                                    # a click
                symbol = self.sch.symbols.get(drag["symbol"])
                if symbol is not None and symbol.kind == "input":
                    self.app.toggle_input(symbol.id)
                self.app.select_symbol(drag["symbol"])
        elif drag["kind"] == "band":
            (x0, y0), (x1, y1) = drag["start"], drag["at"]
            if abs(x1 - x0) < 4 and abs(y1 - y0) < 4:
                self.selection = set()
                self.app.select_symbol(None)
            else:
                lo = ((min(x0, x1) - self.ox) / self.zoom, (min(y0, y1) - self.oy) / self.zoom)
                hi = ((max(x0, x1) - self.ox) / self.zoom, (max(y0, y1) - self.oy) / self.zoom)
                self.selection = {s.id for s in self.sch.symbols.values()
                                  if lo[0] <= s.x and s.x + s.size()[0] <= hi[0]
                                  and lo[1] <= s.y and s.y + s.size()[1] <= hi[1]}
        self.redraw()

    def _double(self, event) -> None:
        gx, gy = self.to_grid(event)
        symbol = self.name_at(gx, gy) or self.symbol_at(gx, gy)
        if symbol is not None and symbol.kind in ("input", "output"):
            name = simpledialog.askstring("Rename", f"New name for {symbol.name}:", initialvalue=symbol.name,
                                          parent=self)
            if name and name != symbol.name:
                self.app.rename_symbol(symbol.id, name.strip())

    def _right(self, event) -> None:
        gx, gy = self.to_grid(event)
        symbol = self.symbol_at(gx, gy)
        if symbol is not None:
            ids = self.selection if symbol.id in self.selection else {symbol.id}
            self.app.schematic_edit(lambda sch: [sch.remove(id) for id in ids])
        elif (wire := self.wire_at(gx, gy)) is not None:
            self.app.schematic_edit(lambda sch: sch.disconnect(wire.target))

    def _pan_start(self, event) -> None:
        self.drag = {"kind": "pan", "last": (event.x, event.y)}

    def _pan_to(self, event) -> None:
        if self.drag and self.drag["kind"] == "pan":
            lx, ly = self.drag["last"]
            self.ox += event.x - lx
            self.oy += event.y - ly
            self.drag["last"] = (event.x, event.y)
            self.redraw()

    def _wheel(self, event, direction: int) -> None:
        if event.state & 0x4:                        # Ctrl: zoom at the cursor
            factor = 1.15 if direction > 0 else 1 / 1.15
            new = max(4.0, min(80.0, self.zoom * factor))
            cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            self.ox = cx - (cx - self.ox) * new / self.zoom
            self.oy = cy - (cy - self.oy) * new / self.zoom
            self.zoom = new
        elif event.state & 0x1:                      # Shift: sideways
            self.ox += direction * 3 * self.zoom
        else:
            self.oy += direction * 3 * self.zoom
        self.redraw()

    def _motion(self, event) -> None:
        if self.drag is not None:
            return
        gx, gy = self.to_grid(event)
        net, text = None, ""
        if (port := self.port_at(gx, gy)) is not None:
            net = port if port.is_output else self.sch.sources.get(port)
            text = f"{port}" + ("" if net is None else f": {self.app.value_of(net).value}")
        elif (wire := self.wire_at(gx, gy)) is not None:
            net = wire.source
            text = f"net from {net}: {self.app.value_of(net).value}"
        elif (symbol := self.symbol_at(gx, gy)) is not None:
            text = f"{symbol.label or symbol.id} ({symbol.id})"
        self.app.set_hover(text)
        if net != self.hover_net:
            self.hover_net = net
            self.redraw()

    def _escape(self) -> None:
        self.drag = None
        if self.selection:
            self.selection = set()
            self.app.select_symbol(None)
        else:
            self.tool.set("select")
        self.redraw()

    def _select_all(self) -> None:
        self.selection = set(self.sch.symbols)
        self.redraw()

    # ------------------------------------------------------------------ edits

    def place(self, gx: float, gy: float) -> None:
        tool = self.tool.get()
        kind = {"input": "input", "output": "output", "const0": "const", "const1": "const"}.get(tool, "gate")
        gate = GATES[tool] if kind == "gate" else None
        name = {"const0": "0", "const1": "1"}.get(tool, "")

        def add(sch: Schematic) -> None:
            s = sch.add(kind, name=name, gate=gate)
            w, h = s.size()
            s.x, s.y = round(gx - w / 2), round(gy - h / 2)
            if not sch.fits(s.id, s.x, s.y):
                raise ValueError("too close to another symbol: leave two free columns and one free row around it")
            self.selection = {s.id}

        self.app.schematic_edit(add)

    def connect(self, a: Port, b: Port) -> None:
        replaced = []
        if self.app.schematic_edit(lambda sch: replaced.append(sch.connect(a, b))) and replaced[0] is not None:
            self.app.say(f"Replaced the wire from {replaced[0]}.")

    def move(self, ids: set[str], dx: int, dy: int) -> None:
        def shift(sch: Schematic) -> None:
            for id in ids:
                sch.symbols[id].x += dx
                sch.symbols[id].y += dy
            for id in ids:
                s = sch.symbols[id]
                if not sch.fits(id, s.x, s.y):
                    raise ValueError("too close to another symbol: leave two free columns and one free row around it")

        self.app.schematic_edit(shift, structural=False)

    def nudge(self, dx: int, dy: int) -> None:
        if self.selection:
            self.move(set(self.selection), dx, dy)

    def delete_selection(self) -> None:
        ids = set(self.selection)
        if ids:
            self.app.schematic_edit(lambda sch: [sch.remove(id) for id in ids])

    # ------------------------------------------------------------------ drawing

    def schedule_redraw(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after_idle(self.redraw)

    def redraw(self) -> None:
        self._job = None
        c, z = self.canvas, self.zoom
        c.delete("all")
        sch = self.sch
        moving = self.drag["ids"] if self.drag and self.drag["kind"] == "move" else set()
        mdx, mdy = self.drag["d"] if moving else (0, 0)

        def at(s: Symbol) -> tuple[int, int]:
            return (s.x + mdx, s.y + mdy) if s.id in moving else (s.x, s.y)

        def port_xy(port: Port) -> tuple[float, float]:
            s = sch.symbols[port.symbol]
            x, y = at(s)
            dx, dy = s.pin_offset(port.pin)
            return x + dx, y + dy

        self._draw_grid()
        if not sch.symbols:
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2, fill="#888", justify="center",
                          text="Pick a symbol in the toolbar and click to place it,\n"
                               "or type an expression in the Expression tab and press Use this.")
            return
        width = max(2.0, z * 0.1)
        wires, junctions = self.routed()
        for w in wires:
            colour = VALUE_COLOURS[self.app.value_of(w.source)]
            thick = width * 2 if w.source == self.hover_net else width
            if moving & {w.source.symbol, w.target.symbol}:
                pts = [port_xy(w.source), port_xy(w.target)]           # straight while dragging
                c.create_line(*[v for p in pts for v in self.to_canvas(*p)], fill=colour, width=width, dash=(4, 3))
            else:
                pts = [v for p in w.points for v in self.to_canvas(*p)]
                c.create_line(*pts, fill=colour, width=thick, dash=() if w.routed else (5, 4),
                              capstyle="round", joinstyle="round")
        if not moving:
            r = max(2.5, z * 0.18)
            for x, y in junctions:
                cx, cy = self.to_canvas(x, y)
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#111", outline="")
        for s in sch.symbols.values():
            self._draw_symbol(s, *at(s))
        self._draw_overlay(port_xy)

    def _draw_grid(self) -> None:
        c, z = self.canvas, self.zoom
        step = 1 if z >= 14 else 2 if z >= 7 else 4
        w, h = c.winfo_width(), c.winfo_height()
        x0, y0 = math.floor(-self.ox / z / step) * step, math.floor(-self.oy / z / step) * step
        r = 1 if z < 30 else 1.5
        y = y0
        while self.oy + y * z < h:
            x = x0
            while self.ox + x * z < w:
                cx, cy = self.to_canvas(x, y)
                c.create_rectangle(cx - r, cy - r, cx + r, cy + r, fill="#d4d4d8", outline="")
                x += step
            y += step

    def _draw_symbol(self, s: Symbol, x: float, y: float) -> None:
        c, z = self.canvas, self.zoom
        P = lambda dx, dy: self.to_canvas(x + dx, y + dy)
        flat = lambda pts: [v for p in pts for v in P(*p)]
        line = max(1.5, z * 0.08)
        font = ("TkDefaultFont", -max(7, round(z * 0.62)), "bold")
        w, h = s.size()
        selected = s.id in self.selection or s.id == self.app.selected_symbol()
        if selected:
            c.create_rectangle(*P(-0.4, -0.4), *P(w + 0.4, h + 0.4), outline=SELECTION, dash=(4, 3), width=2)
        if s.kind == "gate":
            o = outline(s.gate.name, h, STYLES[self.style.get()])
            for pin in s.input_pins():
                _, py = s.pin_offset(pin)
                c.create_line(*flat([(0, py), (o.body_left + 0.3, py)]), width=line)
            c.create_line(*flat([(o.body_right, h / 2), (w, h / 2)]), width=line)
            for poly in o.polygons:
                c.create_polygon(*flat(poly), fill="white", outline=SELECTION if selected else "#111",
                                 width=line * (1.6 if selected else 1))
            for extra in o.lines:
                c.create_line(*flat(extra), fill="#111", width=line)
            if o.bubble:
                bx, by = P(*o.bubble)
                r = z * 0.22
                c.create_oval(bx - r, by - r, bx + r, by + r, fill="white", outline="#111", width=line)
            if o.label:
                c.create_text(*P(2, h / 2), text=o.label, font=font)
        elif s.kind == "input":
            c.create_line(*flat([(2.4, 1), (3, 1)]), width=line)
            on = s.value is Logic.ONE
            c.create_rectangle(*P(0.2, 0.2), *P(2.4, 1.8), outline="#111", width=line,
                               fill="#16a34a" if on else "#4b5563")
            c.create_text(*P(1.3, 1), text=s.value.value, fill="white", font=font)
            c.create_text(*P(-0.3, 1), text=s.name, anchor="e", font=font)
        elif s.kind == "output":
            src = self.sch.sources.get(Port(s.id, "in1"))
            value = self.app.value_of(src) if src else Logic.Z
            c.create_line(*flat([(0, 1), (0.7, 1)]), width=line)
            c.create_oval(*P(0.7, 0.25), *P(2.2, 1.75), outline="#111", width=line,
                          fill=LAMP_COLOURS.get(value, "#f59e0b" if value is Logic.X else "#d4d4d8"))
            c.create_text(*P(2.5, 1), text=s.name, anchor="w", font=font)
        else:
            c.create_line(*flat([(1.4, 1), (2, 1)]), width=line)
            c.create_rectangle(*P(0, 0.3), *P(1.4, 1.7), outline="#111", width=line, fill="#f4f4f5")
            c.create_text(*P(0.7, 1), text=s.name, font=font)
        r = max(2.0, z * 0.14)                       # open input ports, so you can see where to connect
        for pin in s.input_pins():
            if Port(s.id, pin) not in self.sch.sources:
                px, py = P(*s.pin_offset(pin))
                c.create_oval(px - r, py - r, px + r, py + r, outline="#b91c1c", width=1.5, fill="white")

    def _draw_overlay(self, port_xy) -> None:
        c, z = self.canvas, self.zoom
        if self.drag and self.drag["kind"] == "wire":
            start = self.drag["port"]
            r = max(3.0, z * 0.25)
            for s in self.sch.symbols.values():      # ports that would accept this wire
                for port in self.sch.ports(s):
                    if port.is_output != start.is_output and port.symbol != start.symbol:
                        px, py = self.to_canvas(*port_xy(port))
                        c.create_oval(px - r, py - r, px + r, py + r, outline="#16a34a", width=2)
            sx, sy = self.to_canvas(*port_xy(start))
            c.create_line(sx, sy, *self.drag["at"], fill="#111", width=2, dash=(4, 3))
        elif self.drag and self.drag["kind"] == "band":
            c.create_rectangle(*self.drag["start"], *self.drag["at"], outline=SELECTION, dash=(4, 3))
