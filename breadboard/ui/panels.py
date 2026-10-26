"""Side panel tabs: Problems, Gate (truth table of the selected gate) and Expression (design.md §4.4, §6.8)."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import font, ttk
from typing import Callable

from ..expr import ParseError, parse, to_text
from ..layout import chips_needed
from ..logic import GATES, Gate, Logic, truth_table
from ..netlist import MAX_INPUTS, Netlist

HIGHLIGHT = "#fde68a"
LIBRARY = [name for name in GATES if name != "BUF"]


def wrap_to_width(frame: ttk.Frame, label: ttk.Label) -> None:
    """Wrap the label's text at the frame's current width (it changes with the window)."""
    frame.bind("<Configure>", lambda e: label.configure(wraplength=max(100, e.width - 24)), add="+")


class TruthTableView(ttk.Frame):
    """A truth table: one column per input, a separator, one column per output."""

    def __init__(self, master, height: int = 10):
        super().__init__(master)
        self.tree = ttk.Treeview(self, show="headings", height=height, selectmode="none")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.tree.tag_configure("now", background=HIGHLIGHT)
        self._font = font.nametofont("TkDefaultFont")

    def show(self, inputs: list[str], outputs: list[str], rows: list[tuple[list[str], list[str]]],
             highlight: int | None = None) -> None:
        columns = [f"i{k}" for k in range(len(inputs))] + ["sep"] + [f"o{k}" for k in range(len(outputs))]
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(columns=columns)
        pad = self._font.measure("00")
        for column, title in zip(columns, inputs + ["│"] + outputs):
            width = self._font.measure("│") + pad if column == "sep" else max(self._font.measure(title) + pad, 3 * pad)
            self.tree.heading(column, text=title, anchor="center")
            self.tree.column(column, width=width, minwidth=width, anchor="center", stretch=column != "sep")
        for i, (ins, outs) in enumerate(rows):
            item = self.tree.insert("", "end", values=ins + ["│"] + outs, tags=("now",) if i == highlight else ())
            if i == highlight:
                self.tree.see(item)

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(columns=[])


class ProblemsPanel(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.list = tk.Listbox(self, borderwidth=0, highlightthickness=0, activestyle="none")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=scroll.set)
        self.list.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def show(self, problems: list[str]) -> None:
        self.list.delete(0, "end")
        for problem in problems:
            self.list.insert("end", problem)
        if not problems:
            self.list.insert("end", "No problems found.")
            self.list.itemconfigure(0, foreground="#777")


@dataclass
class GateInfo:
    """What the Gate tab shows for a selected gate."""
    title: str
    gate: Gate
    input_names: list[str]
    output_name: str
    input_values: list[Logic] | None = None    # live values, or None
    output_value: Logic | None = None


@dataclass
class PinoutInfo:
    title: str
    rows: list[tuple[str, str, str]]           # pin, name, current value


class GatePanel(ttk.Frame):
    SELECTED = "Selected gate"

    def __init__(self, master):
        super().__init__(master, padding=8)
        self.choice = tk.StringVar(value=self.SELECTED)
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Show:").pack(side="left")
        menu = ttk.Combobox(top, textvariable=self.choice, values=[self.SELECTED] + LIBRARY,
                            state="readonly", width=16)
        menu.pack(side="left", padx=(6, 0))
        menu.bind("<<ComboboxSelected>>", lambda _: self._render())
        bold = font.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        self.title = ttk.Label(self, font=bold)
        self.title.pack(anchor="w", pady=(8, 4))
        self.table = TruthTableView(self, height=9)
        self.table.pack(fill="both", expand=True)
        self.now = ttk.Label(self, justify="left")
        self.now.pack(anchor="w", pady=(6, 0))
        wrap_to_width(self, self.now)
        self.selected: GateInfo | PinoutInfo | None = None

    def set_selected(self, info: GateInfo | PinoutInfo | None, switch: bool = False) -> None:
        self.selected = info
        if switch:
            self.choice.set(self.SELECTED)
        self._render()

    def _render(self) -> None:
        choice = self.choice.get()
        if choice != self.SELECTED:
            gate = GATES[choice]
            info = GateInfo(f"{choice} gate", gate, [chr(ord("A") + i) for i in range(gate.arity)], "Y")
        else:
            info = self.selected
        if info is None:
            self.title.configure(text="Nothing selected")
            self.table.clear()
            self.now.configure(text="Click a gate (or a chip pin on the board) to see its truth table.")
        elif isinstance(info, PinoutInfo):
            self.title.configure(text=info.title)
            self.table.show(["Pin", "Name"], ["Value"], [([p, n], [v]) for p, n, v in info.rows])
            self.now.configure(text="")
        else:
            self.title.configure(text=info.title)
            rows = truth_table(info.gate)
            highlight = None
            if info.input_values is not None and all(v.known() for v in info.input_values):
                highlight = next(i for i, (ins, _) in enumerate(rows) if list(ins) == info.input_values)
            self.table.show(info.input_names, [info.output_name],
                            [([v.value for v in ins], [out.value]) for ins, out in rows], highlight)
            if info.input_values is None:
                self.now.configure(text="")
            else:
                ins = ", ".join(f"{n} = {v.value}" for n, v in zip(info.input_names, info.input_values))
                self.now.configure(text=f"Now: {ins} → {info.output_name} = {info.output_value.value}")


class ExpressionPanel(ttk.Frame):
    """Type equations, see how they were read and their truth table, and use them as the circuit."""

    def __init__(self, master, on_use: Callable[[Netlist, str], None], on_from_circuit: Callable[[], str]):
        super().__init__(master, padding=8)
        self.on_use, self.on_from_circuit = on_use, on_from_circuit
        mono = font.nametofont("TkFixedFont")
        self.text = tk.Text(self, height=4, width=30, wrap="word", undo=True, font=mono)
        self.text.pack(fill="x")
        self.text.tag_configure("error", background="#fca5a5")
        self.text.bind("<<Modified>>", self._modified)
        symbols = ttk.Frame(self)
        symbols.pack(fill="x", pady=(6, 0))
        for symbol in ("·", "+", "⊕", "'", "¬"):
            ttk.Button(symbols, text=symbol, width=2, command=lambda s=symbol: self._insert(s)).pack(side="left")
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(4, 0))
        ttk.Button(actions, text="Use this", command=self._use).pack(side="right")
        ttk.Button(actions, text="From circuit", command=self._from_circuit).pack(side="right", padx=(0, 4))
        self.message = ttk.Label(self, justify="left")
        self.message.pack(anchor="w", pady=(8, 0), fill="x")
        wrap_to_width(self, self.message)
        self.table = TruthTableView(self, height=10)
        self.table.pack(fill="both", expand=True, pady=(6, 0))
        help = ttk.Label(self, text="+ | OR    · * & or nothing: AND    ⊕ ^ XOR    ' ¬ ! ~ NOT\n"
                                    "Names start with a capital: A, B, Cin, X1. One equation per line or ;",
                         foreground="#666", justify="left")
        help.pack(anchor="w", pady=(6, 0))
        wrap_to_width(self, help)
        self.netlist: Netlist | None = None
        self.rows: list = []
        self._job = None
        self.live: dict[str, Logic] | None = None

    def _insert(self, symbol: str) -> None:
        self.text.insert("insert", symbol)
        self.text.focus_set()

    def _modified(self, _event=None) -> None:
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if self._job is not None:
                self.after_cancel(self._job)
            self._job = self.after(200, self.reparse)

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, text: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.reparse()

    def reparse(self) -> None:
        self._job = None
        self.text.tag_remove("error", "1.0", "end")
        self.netlist, self.rows = None, []
        text = self.get()
        if not text.strip():
            self.message.configure(text="Type an expression such as F = A + B·C', or press From circuit.",
                                   foreground="")
            self.table.clear()
            return
        try:
            program = parse(text)
        except ParseError as error:
            at = min(error.position, len(text) - 1)          # past the end: mark the last character
            self.text.tag_add("error", f"1.0+{at}c", f"1.0+{at + 1}c")
            text = str(error)
            self.message.configure(text=text[:1].upper() + text[1:], foreground="#b91c1c")
            self.table.clear()
            return
        netlist = Netlist.from_program(program)
        fused = netlist.fused()
        lines = [f"Read as: {eq.name} = {to_text(eq.expr)}" for eq in program.equations]
        counts = fused.gate_counts()
        gates = ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))
        lines.append(f"{len(netlist.inputs)} inputs, {len(netlist.outputs)} outputs, "
                     f"{sum(counts.values())} gates{': ' + gates if gates else ''}")
        chips = chips_needed(fused)
        if chips:
            lines.append("Chips: " + ", ".join(f"{n} × {name}" if n > 1 else name for name, n in chips.items()))
        if netlist.has_feedback():
            lines.append("This circuit has feedback: X rows depend on the previous state. "
                         "Use it and flip the switches to try it.")
        if len(netlist.inputs) > MAX_INPUTS:
            lines.append(f"No truth table: more than {MAX_INPUTS} inputs.")
            self.table.clear()
        else:
            self.rows = netlist.truth_table()
        self.message.configure(text="\n".join(lines), foreground="")
        self.netlist = netlist
        self._show_table()

    def set_live(self, values: dict[str, Logic] | None) -> None:
        """Input values of the circuit built from this text, or None if it isn't the current one."""
        if values != self.live:
            self.live = values
            self._show_table()

    def _show_table(self) -> None:
        if self.netlist is None or not self.rows:
            return
        highlight = None
        if self.live is not None and all(name in self.live for name in self.netlist.inputs):
            now = tuple(self.live[name] for name in self.netlist.inputs)
            highlight = next((i for i, (ins, _) in enumerate(self.rows) if ins == now), None)
        self.table.show(self.netlist.inputs, self.netlist.outputs,
                        [([v.value for v in ins], [v.value for v in outs]) for ins, outs in self.rows], highlight)

    def _use(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self.reparse()
        if self.netlist is not None:
            self.on_use(self.netlist, self.get())

    def _from_circuit(self) -> None:
        try:
            text = self.on_from_circuit()
        except ValueError as error:
            self.message.configure(text=f"Can't write this circuit as an expression: {error}.",
                                   foreground="#b91c1c")
            return
        self.set(text)
