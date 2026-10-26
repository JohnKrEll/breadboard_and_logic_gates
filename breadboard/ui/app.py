"""The main window: one circuit, a breadboard view and a schematic view (design.md §4, §7.1)."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk
from typing import Callable

from ..board import Breadboard, Chip, LogicInput, PowerSupply
from ..circuit import Circuit, GateNode, InputNode, Net
from ..derive import derive
from ..extract import Extraction, extract, gate_id, led_id, switch_id
from ..layout import Layout, LayoutError, layout
from ..logic import Logic
from ..netlist import Netlist
from ..schematic import Port, Schematic
from .board_view import VALUE_COLOURS, BoardView
from .panels import ExpressionPanel, GateInfo, GatePanel, PinoutInfo, ProblemsPanel
from .schematic_view import SchematicView

UNDO_LIMIT = 100
HAND_WORK = "The breadboard will be rebuilt from the schematic, and its hand-placed wiring will be lost."


def new_board() -> Breadboard:
    board = Breadboard()
    board.place(PowerSupply("T+1", "T-1"))
    return board


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.board = new_board()
        self.schematic = Schematic()
        self.master = "board"                       # whose document the circuit is (§7.1)
        self.extraction: Extraction | None = None   # the board's schematic, while the board is master
        self.generated: Layout | None = None        # the board built from the schematic
        self.version = 0                            # bumped by every structural schematic change
        self.generated_version = -1
        self.sim: tuple[Circuit, dict[str, InputNode], dict[str, Net]] | None = None
        self.expression_link: tuple[str, int] | None = None
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.selection: dict = {}                   # "symbol": id, "chip": (chip, index), "pinout": chip
        self.view = tk.StringVar(value="board")
        self.status = tk.StringVar()
        self.hover = tk.StringVar()
        self._build()
        self.extract_board()
        self.show_view()
        self._divider = self.paned.bind("<Configure>", self._place_divider, add="+")

    def _place_divider(self, event) -> None:
        """Once the window has its size: about three quarters of the width for the board or schematic."""
        if event.width > 1:
            self.paned.unbind("<Configure>", self._divider)
            self.paned.sashpos(0, int(event.width * 0.74))

    # ------------------------------------------------------------------ window

    def _build(self) -> None:
        root = self.root
        root.title("Breadboard simulator")
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=font.nametofont("TkDefaultFont").metrics("linespace") + 4)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = int(sw * 0.8), int(sh * 0.8)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
        root.minsize(int(sw * 0.4), int(sh * 0.4))

        menu = tk.Menu(root)
        file = tk.Menu(menu, tearoff=False)
        file.add_command(label="New board", command=self.clear_board)
        file.add_command(label="New schematic", command=self.new_schematic)
        file.add_separator()
        file.add_command(label="Open schematic…", command=self.open_schematic, accelerator="Ctrl+O")
        file.add_command(label="Save schematic…", command=self.save_schematic, accelerator="Ctrl+S")
        file.add_separator()
        file.add_command(label="Quit", command=root.destroy)
        view = tk.Menu(menu, tearoff=False)
        view.add_radiobutton(label="Breadboard", value="board", variable=self.view, command=self.show_view)
        view.add_radiobutton(label="Schematic", value="schematic", variable=self.view, command=self.show_view,
                             accelerator="Ctrl+Tab")
        view.add_command(label="Side panel", command=self.toggle_side, accelerator="F9")
        menu.add_cascade(label="File", menu=file)
        menu.add_cascade(label="View", menu=view)
        root.configure(menu=menu)

        bar = ttk.Frame(root, padding=(6, 6, 6, 4))
        bar.grid(row=0, column=0, sticky="ew")
        for value, label in (("board", "Breadboard"), ("schematic", "Schematic")):
            ttk.Radiobutton(bar, text=label, value=value, variable=self.view, style="Toolbutton",
                            command=self.show_view).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        tools = ttk.Frame(bar)
        tools.pack(side="left", fill="x", expand=True)

        self.paned = ttk.Panedwindow(root, orient="horizontal")
        self.paned.grid(row=1, column=0, sticky="nsew")
        views = ttk.Frame(self.paned)
        views.rowconfigure(0, weight=1)
        views.columnconfigure(0, weight=1)
        self.board_view = BoardView(views, self)
        self.schematic_view = SchematicView(views, self)
        for v in (self.board_view, self.schematic_view):
            v.grid(row=0, column=0, sticky="nsew")
        self.toolbars = {"board": self.board_view.toolbar(tools), "schematic": self.schematic_view.toolbar(tools)}
        self.side = ttk.Notebook(self.paned)
        self.problems_panel = ProblemsPanel(self.side)
        self.gate_panel = GatePanel(self.side)
        self.expression_panel = ExpressionPanel(self.side, self.use_expression, self.circuit_expression)
        self.side.add(self.problems_panel, text="Problems")
        self.side.add(self.gate_panel, text="Gate")
        self.side.add(self.expression_panel, text="Expression")
        self.paned.add(views, weight=3)
        self.paned.add(self.side, weight=1)
        self._side_visible = True

        status = ttk.Frame(root, padding=(8, 2, 8, 6))
        status.grid(row=2, column=0, sticky="ew")
        self.status_label = ttk.Label(status, textvariable=self.status)
        self.status_label.pack(side="left")
        ttk.Label(status, textvariable=self.hover, foreground="#555").pack(side="right")
        legend = ttk.Frame(status)
        legend.pack(side="right", padx=20)
        size = font.nametofont("TkDefaultFont").metrics("linespace") // 2
        for value, name in ((Logic.ONE, "1"), (Logic.ZERO, "0"), (Logic.X, "X unknown"), (Logic.Z, "Z floating")):
            tk.Canvas(legend, width=size, height=size, background=VALUE_COLOURS[value],
                      highlightthickness=0).pack(side="left", padx=(8, 3))
            ttk.Label(legend, text=name).pack(side="left")
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)

        root.bind_all("<Control-Tab>", lambda _: self.toggle_view())
        root.bind_all("<F9>", lambda _: self.toggle_side())
        for canvas in (self.board_view.canvas, self.schematic_view.canvas):
            canvas.bind("<Control-s>", lambda _: self.save_schematic())
            canvas.bind("<Control-o>", lambda _: self.open_schematic())
        sc = self.schematic_view.canvas
        sc.bind("<Control-z>", lambda _: self.undo())
        sc.bind("<Control-y>", lambda _: self.redo())
        sc.bind("<Control-Z>", lambda _: self.redo())

    def toggle_view(self) -> str:
        self.view.set("schematic" if self.view.get() == "board" else "board")
        self.show_view()
        return "break"

    def toggle_side(self) -> None:
        if self._side_visible:
            self.paned.forget(self.side)
        else:
            self.paned.add(self.side, weight=1)
        self._side_visible = not self._side_visible

    def show_view(self) -> None:
        view = self.view.get()
        self.set_hover("")
        if view == "board" and self.master == "schematic":
            self.ensure_generated_board()
        for name, bar in self.toolbars.items():
            if name == view:
                bar.pack(side="left")
            else:
                bar.pack_forget()
        (self.board_view if view == "board" else self.schematic_view).tkraise()
        if view == "board":
            self.board_view.sync_size()
            self.board_view.cancel()
        else:
            self.say("Schematic view. " + ("Drawn from the breadboard." if self.master == "board"
                                           else "This is the circuit; the breadboard is built from it."))
        self.refresh()

    def say(self, text: str, error: bool = False) -> None:
        self.status.set(text)
        self.status_label.configure(foreground="#b91c1c" if error else "")

    def set_hover(self, text: str) -> None:
        self.hover.set(text)

    def refresh(self) -> None:
        if self.view.get() == "board":
            self.board_view.schedule_redraw()
        else:
            self.schematic_view.schedule_redraw()
        self.update_panels()

    # ------------------------------------------------------------------ the breadboard

    def has_hand_work(self) -> bool:
        return self.master == "board" and any(not isinstance(p, PowerSupply) for p in self.board.parts)

    def board_edit(self, change: Callable[[Breadboard], object]) -> bool:
        """A structural change on the board. Makes the board the master (§7.1)."""
        try:
            change(self.board)
        except ValueError as error:
            self.say(str(error)[:1].upper() + str(error)[1:] + ".", error=True)
            self.board_view.redraw()
            return False
        previous = self.translated_schematic() if self.master == "schematic" else self.schematic
        self.master = "board"
        self.generated, self.sim, self.expression_link = None, None, None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.extract_board(previous)
        self.refresh()
        return True

    def extract_board(self, previous: Schematic | None = None) -> None:
        self.extraction = extract(self.board, previous if previous is not None else self.schematic)
        self.schematic = self.extraction.schematic
        self.schematic_view.invalidate()

    def translated_schematic(self) -> Schematic:
        """The schematic with the ids extraction will give the generated board's parts,
        so its positions carry over when the board becomes the master."""
        gen, ids = self.generated, {}
        if gen is None:
            return Schematic()
        for s in self.schematic.symbols.values():
            if s.kind == "input" and s.name in gen.inputs:
                ids[s.id] = switch_id(gen.inputs[s.name])
            elif s.kind == "output" and s.name in gen.leds:
                ids[s.id] = led_id(gen.leds[s.name])
            elif s.kind == "gate" and s.id in gen.gates:
                ids[s.id] = gate_id(*gen.gates[s.id])
            elif s.kind == "const":
                ids[s.id] = f"k{s.name}"
        return self.schematic.renamed(ids)

    def ensure_generated_board(self) -> None:
        """While the schematic is the master, the board is built from it when it's shown."""
        if self.generated is not None and self.generated_version == self.version:
            return
        self.generated_version = self.version
        try:
            result = layout(self.schematic.to_netlist())
        except LayoutError as error:
            self.generated = None
            self.board = new_board()
            self.say(f"This circuit can't be built on a breadboard: {error}.", error=True)
            return
        self.generated, self.board = result, result.board
        for s in self.schematic.symbols.values():
            if s.kind == "input" and s.name in result.inputs and result.inputs[s.name].value is not s.value:
                self.board.set(result.inputs[s.name], s.value)
        if self.sim is not None:                     # start in the schematic's state, so a latch keeps it
            values = {n.name: n.value for n in self.sim[0].nodes if isinstance(n, GateNode)}
            for id, (chip, index) in result.gates.items():
                if id in values:
                    self.board.nodes[chip][index].value = values[id]
            self.board.circuit.settle()

    def toggle_switch(self, part: LogicInput) -> None:
        self.board.toggle(part)
        if self.master == "schematic":
            symbol = self.schematic.by_name(part.label)
            if symbol is not None:
                symbol.value = part.value
                self.sim_set(symbol.name, symbol.value)
        elif (symbol := self.schematic.symbols.get(switch_id(part))) is not None:
            symbol.value = part.value
        self.refresh()

    def clear_board(self) -> None:
        if self.master == "schematic" and self.schematic.symbols:
            question = "The board is built from the schematic. Clearing it makes the empty board the circuit, " \
                       "and the schematic will be empty too. Continue?"
        elif self.has_hand_work():
            question = "Remove everything from the board?"
        else:
            question = None
        if question and not messagebox.askokcancel("Clear board", question, parent=self.root):
            return
        self.board = new_board()
        self.schematic = Schematic()
        self.master, self.generated, self.sim, self.expression_link = "board", None, None, None
        self.selection = {}
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.extract_board()
        self.board_view.sync_size()
        self.refresh()

    # ------------------------------------------------------------------ the schematic

    def take_over_from_board(self) -> bool:
        """Make the schematic the master, asking first if that throws away work on the board."""
        if self.has_hand_work() and not messagebox.askokcancel("Edit the schematic", HAND_WORK + " Continue?",
                                                                parent=self.root):
            return False
        state = {}                                   # the board's gate values, so a latch keeps its state
        if self.extraction is not None:
            state = {id: self.board.nodes[chip][index].value
                     for id, (chip, index) in self.extraction.gates.items() if chip in self.board.nodes}
        self.master, self.extraction, self.generated = "schematic", None, None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.sim = None
        self.resimulate(state)
        return True

    def schematic_edit(self, change: Callable[[Schematic], object], structural: bool = True) -> bool:
        if structural and self.master == "board" and not self.take_over_from_board():
            return False
        snapshot = self.schematic.to_dict()
        try:
            change(self.schematic)
        except ValueError as error:
            self.schematic = Schematic.from_dict(snapshot)
            self._schematic_replaced()
            self.say(str(error)[:1].upper() + str(error)[1:] + ".", error=True)
            self.refresh()
            return False
        self.undo_stack.append(snapshot)
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()
        if structural:
            self.version += 1
            self.resimulate()
        self.schematic_view.invalidate()
        self.refresh()
        return True

    def _schematic_replaced(self) -> None:
        if self.extraction is not None:
            self.extraction.schematic = self.schematic
        self.schematic_view.invalidate()

    def resimulate(self, state: dict[str, Logic] | None = None) -> None:
        """Simulate the schematic itself, carrying gate values over so latches keep their state.
        `state` gives the values to start from instead (gate symbol id -> value)."""
        if state is not None:
            old = state
        else:
            old = {n.name: n.value for n in self.sim[0].nodes if isinstance(n, GateNode)} if self.sim else {}
        circuit, inputs, nets = self.schematic.to_netlist().to_circuit()
        for node in circuit.nodes:
            if isinstance(node, GateNode) and node.name in old:
                node.value = old[node.name]
        for s in self.schematic.symbols.values():
            if s.kind == "input":
                inputs[s.name].setting = s.value
        circuit.settle()
        self.sim = (circuit, inputs, nets)

    def sim_set(self, name: str, value: Logic) -> None:
        if self.sim is not None and name in self.sim[1]:
            self.sim[0].set_input(self.sim[1][name], value)

    def value_of(self, port: Port) -> Logic:
        if self.master == "board":
            net = self.extraction.live.get(port) if self.extraction else None
            return net.value if net is not None else Logic.Z
        if self.sim is None:
            return Logic.Z
        net = self.sim[2].get(self.schematic.signal(port, port))
        return net.value if net is not None else Logic.Z

    def toggle_input(self, id: str) -> None:
        symbol = self.schematic.symbols[id]
        if self.master == "board":
            part = self.extraction.parts.get(id)
            if isinstance(part, LogicInput):
                self.board.toggle(part)
                symbol.value = part.value
        else:
            symbol.value = Logic.ZERO if symbol.value is Logic.ONE else Logic.ONE
            self.sim_set(symbol.name, symbol.value)
            if self.generated is not None and self.generated_version == self.version \
                    and symbol.name in self.generated.inputs:
                self.board.set(self.generated.inputs[symbol.name], symbol.value)
        self.refresh()

    def rename_symbol(self, id: str, name: str) -> None:
        if self.master == "board":
            try:
                self.schematic.rename(id, name)
            except ValueError as error:
                self.say(str(error)[:1].upper() + str(error)[1:] + ".", error=True)
                return
            part = self.extraction.parts.get(id)
            if part is not None:
                part.label = name                    # the board part carries the name (§3.3)
            self.extract_board(self.schematic)
            self.refresh()
        else:
            self.schematic_edit(lambda sch: sch.rename(id, name))

    def undo(self) -> None:
        self._step(self.undo_stack, self.redo_stack, "undo")

    def redo(self) -> None:
        self._step(self.redo_stack, self.undo_stack, "redo")

    def _step(self, source: list[dict], target: list[dict], what: str) -> None:
        if not source:
            self.say(f"Nothing to {what}.")
            return
        target.append(self.schematic.to_dict())
        self.schematic = Schematic.from_dict(source.pop())
        self._schematic_replaced()
        if self.master == "schematic":
            self.version += 1
            self.resimulate()
        self.refresh()

    def new_schematic(self) -> None:
        if self.master == "schematic" and self.schematic.symbols and not messagebox.askokcancel(
                "New schematic", "Start a new, empty schematic?", parent=self.root):
            return
        if self.master == "board" and not self.take_over_from_board():
            return
        self._replace_schematic(Schematic())

    def _replace_schematic(self, schematic: Schematic) -> None:
        if self.master == "schematic" and self.schematic.symbols:
            self.undo_stack.append(self.schematic.to_dict())
            self.redo_stack.clear()
        self.schematic, self.master, self.extraction, self.generated = schematic, "schematic", None, None
        self.version += 1
        self.sim = None
        self.selection = {}
        self.resimulate()
        self.schematic_view.invalidate()
        self.view.set("schematic")
        self.show_view()
        self.root.after_idle(self.schematic_view.fit)

    def save_schematic(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.root, title="Save schematic", defaultextension=".json",
                                            filetypes=[("Schematic", "*.json"), ("All files", "*")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.schematic.to_dict(), f, indent=1, ensure_ascii=False)
            self.say(f"Saved {path}.")

    def open_schematic(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Open schematic",
                                          filetypes=[("Schematic", "*.json"), ("All files", "*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                schematic = Schematic.from_dict(json.load(f))
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror("Open schematic", f"Couldn't open {path}:\n{error}", parent=self.root)
            return
        if self.master == "board" and not self.take_over_from_board():
            return
        self._replace_schematic(schematic)
        self.say(f"Opened {path}.")

    # ------------------------------------------------------------------ expressions

    def use_expression(self, netlist: Netlist, text: str) -> None:
        if self.master == "board" and not self.take_over_from_board():
            return
        self._replace_schematic(Schematic.from_netlist(netlist.fused()))
        self.expression_link = (text, self.version)
        self.say("The expression is now the circuit. Switch to the breadboard view to see it built.")

    def circuit_expression(self) -> str:
        netlist = self.schematic.to_netlist()
        if not netlist.outputs:
            raise ValueError("it has no outputs")
        return derive(netlist)

    # ------------------------------------------------------------------ selection and panels

    def select_symbol(self, id: str | None) -> None:
        self.selection = {}
        symbol = self.schematic.symbols.get(id) if id else None
        if symbol is not None and symbol.kind == "gate":
            self.selection["symbol"] = id
            if (chip := self.chip_of(id)) is not None:
                self.selection["chip"] = chip
            self.side.select(self.gate_panel)
        self.gate_panel.set_selected(self.gate_info(), switch=True)
        self.refresh()

    def select_board_pin(self, chip: Chip, pin: int) -> None:
        index = chip.spec.gate_at(pin)
        if index is None:
            self.selection = {"pinout": chip}
        else:
            self.selection = {"chip": (chip, index)}
            if (id := self.symbol_of(chip, index)) is not None:
                self.selection["symbol"] = id
        self.side.select(self.gate_panel)
        self.gate_panel.set_selected(self.gate_info(), switch=True)
        self.refresh()

    def chip_of(self, id: str) -> tuple[Chip, int] | None:
        if self.master == "board" and self.extraction is not None:
            return self.extraction.gates.get(id)
        if self.generated is not None and self.generated_version == self.version:
            return self.generated.gates.get(id)
        return None

    def symbol_of(self, chip: Chip, index: int) -> str | None:
        if self.master == "board" and self.extraction is not None:
            return next((id for id, ci in self.extraction.gates.items() if ci == (chip, index)), None)
        if self.generated is not None:
            return next((id for id, ci in self.generated.gates.items() if ci == (chip, index)), None)
        return None

    def _sync_selection(self) -> None:
        """Keep the symbol and chip halves of the selection pointing at the same gate,
        also after the board was generated again."""
        selection = self.selection
        if "symbol" in selection:
            if selection["symbol"] not in self.schematic.symbols:
                self.selection = {}
            elif (chip := self.chip_of(selection["symbol"])) is not None:
                selection["chip"] = chip
            else:
                selection.pop("chip", None)
        elif "chip" in selection and (id := self.symbol_of(*selection["chip"])) is not None:
            selection["symbol"] = id

    def selected_symbol(self) -> str | None:
        id = self.selection.get("symbol")
        return id if id in self.schematic.symbols else None

    def selected_board_gate(self) -> tuple[Chip, int] | None:
        return self.selection.get("chip")

    def gate_info(self) -> GateInfo | PinoutInfo | None:
        if self.view.get() == "board":
            if (chip := self.selection.get("pinout")) is not None and chip in self.board.parts:
                names = chip.spec.pin_names()
                rows = [(str(pin), names.get(pin, "–"), self._pin_value(chip, pin).value)
                        for pin in range(1, chip.spec.pin_count + 1)]
                return PinoutInfo(f"{chip.spec.name} at column {chip.column}: pinout", rows)
            if (selected := self.selection.get("chip")) is not None and selected[0] in self.board.parts:
                chip, index = selected
                gate, inputs, output = chip.spec.gates[index]
                names = chip.spec.pin_names()
                return GateInfo(f"{chip.spec.name} at column {chip.column}, gate {index + 1} ({gate.name})", gate,
                                [f"{names[p]} (pin {p})" for p in inputs], f"{names[output]} (pin {output})",
                                [self._pin_value(chip, p) for p in inputs], self._pin_value(chip, output))
            return None
        id = self.selected_symbol()
        if id is None:
            return None
        s = self.schematic.symbols[id]
        values = [self.value_of(src) if (src := self.schematic.sources.get(Port(id, pin))) else Logic.Z
                  for pin in s.input_pins()]
        title = f"{s.gate.name} gate {id}"
        if (chip := self.chip_of(id)) is not None:
            title += f": {chip[0].spec.name} at column {chip[0].column}, gate {chip[1] + 1}"
        return GateInfo(title, s.gate, [pin for pin in s.input_pins()], "out", values, self.value_of(Port(id, "out")))

    def _pin_value(self, chip: Chip, pin: int) -> Logic:
        net = self.board.net_at(chip.pin_hole(pin))
        return net.value if net is not None else Logic.Z

    def problems(self) -> list[str]:
        if self.master == "board":
            return self.board.diagnose() + (self.extraction.problems if self.extraction else [])
        problems = self.schematic.problems()
        if self.sim is not None:
            problems += [f"oscillation at {node.name}" for node in sorted(self.sim[0].oscillating, key=lambda n: n.name)]
        if self.view.get() == "schematic":
            problems += [f"the wire from {w.source} to {w.target} couldn't be routed: move symbols apart"
                         for w in self.schematic_view.unrouted()]
        return problems

    def update_panels(self) -> None:
        self._sync_selection()
        problems = self.problems()
        self.problems_panel.show(problems)
        self.side.tab(self.problems_panel, text=f"Problems ({len(problems)})" if problems else "Problems")
        self.gate_panel.set_selected(self.gate_info())
        live = None
        if self.master == "schematic" and self.expression_link == (self.expression_panel.get(), self.version):
            live = {s.name: s.value for s in self.schematic.symbols.values() if s.kind == "input"}
        self.expression_panel.set_live(live)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
