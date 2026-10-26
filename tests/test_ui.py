"""Drives the real App in a hidden window. Skipped where there is no display."""
import json
import os
import tempfile
import tkinter as tk
import unittest
from unittest import mock

from breadboard.board import Chip, Led, LogicInput, Wire
from breadboard.logic import Logic
from breadboard.schematic import Port

O, I = Logic.ZERO, Logic.ONE


class UiTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.root.withdraw()
        from breadboard.ui.app import App
        self.app = App(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.root.update_idletasks()                      # run queued redraws before the window goes
        self.root.destroy()

    # ------------------------------------------------------------------ helpers

    def board_tool(self, tool, *holes, chip=None):
        view = self.app.board_view
        view.tool.set(tool)
        if chip:
            from breadboard.ui.board_view import CHIP_LABELS
            view.chip.set(next(label for label, key in CHIP_LABELS.items() if key == chip))
        for hole in holes:
            view.click(hole)

    def build_half_adder(self):
        t = self.board_tool
        t("wire", "T+3", "B+1"); t("wire", "T-3", "B-1")
        t("chip", "c5", chip="7486"); t("wire", "a5", "T+2"); t("wire", "j11", "B-2")
        t("chip", "h15", chip="7408"); t("wire", "a15", "T+5"); t("wire", "j21", "B-6")
        t("input", "j5", "j6")
        t("wire", "h5", "h15"); t("wire", "h6", "h16")
        t("led", "g7", "B-5"); t("wire", "g17", "g25"); t("led", "h25", "h26")
        t("resistor", "i26", "B-8")
        board = self.app.board
        return board.part_at("j5"), board.part_at("j6"), board.part_at("g7"), board.part_at("h25")

    def leds(self):
        return {part.label or part.anode: self.app.board.led(part) for part in self.app.board.parts
                if isinstance(part, Led)}

    def symbol(self, name):
        return self.app.schematic.by_name(name)

    def place(self, tool, x, y):
        view = self.app.schematic_view
        view.tool.set(tool)
        view.place(x, y)
        return self.app.schematic.symbols[next(iter(view.selection))]

    # ------------------------------------------------------------------ tests

    def test_hand_built_board_seen_as_a_schematic(self):
        A, B, s, c = self.build_half_adder()
        self.assertEqual(self.app.board.diagnose(), [])
        self.board_tool("wire")
        self.app.board_view.click("j5")                  # clicking a switch flips it, whatever the tool
        self.assertEqual((self.app.board.led(s), self.app.board.led(c)), (I, O))
        self.app.view.set("schematic")
        self.app.show_view()
        self.app.schematic_view.redraw()
        kinds = sorted((x.kind, x.label) for x in self.app.schematic.symbols.values())
        self.assertEqual(kinds, [("gate", "AND"), ("gate", "XOR"), ("input", "A"), ("input", "B"),
                                 ("output", "F"), ("output", "G")])
        self.app.toggle_input(self.symbol("B").id)        # flips the board's switch
        self.assertIs(B.value, I)
        self.assertEqual((self.app.board.led(s), self.app.board.led(c)), (O, I))
        lamp = self.symbol("G")
        self.assertIs(self.app.value_of(self.app.schematic.sources[Port(lamp.id, "in1")]), I)
        self.assertEqual(self.app.master, "board")

    def test_editing_the_schematic_of_a_hand_built_board_asks_first(self):
        self.build_half_adder()
        self.app.view.set("schematic")
        self.app.show_view()
        with mock.patch("tkinter.messagebox.askokcancel", return_value=False) as ask:
            self.app.schematic_view.tool.set("input")
            self.app.schematic_view.place(-20, -20)
            ask.assert_called_once()
        self.assertEqual(self.app.master, "board")
        self.assertIsNone(self.symbol("C"))
        with mock.patch("tkinter.messagebox.askokcancel", return_value=True):
            new = self.place("input", -20, -20)
        self.assertEqual((self.app.master, new.name), ("schematic", "C"))
        self.app.view.set("board")
        self.app.show_view()                              # the board is rebuilt from the schematic
        self.assertIsNotNone(self.app.generated)
        self.assertEqual({p.label for p in self.app.board.parts if isinstance(p, LogicInput)}, {"A", "B", "C"})

    def test_design_in_the_schematic(self):
        self.app.view.set("schematic")
        self.app.show_view()
        a, b = self.place("input", 0, 0), self.place("input", 0, 6)
        g = self.place("NAND", 12, 3)
        f = self.place("output", 24, 3)
        view = self.app.schematic_view
        view.connect(Port(a.id, "out"), Port(g.id, "in1"))
        view.connect(Port(g.id, "in2"), Port(b.id, "out"))
        view.connect(Port(g.id, "out"), Port(f.id, "in1"))
        self.assertEqual(self.app.master, "schematic")
        self.assertEqual(self.app.problems(), [])
        lamp = lambda: self.app.value_of(Port(g.id, "out"))
        self.assertIs(lamp(), I)
        self.app.toggle_input(a.id)
        self.app.toggle_input(b.id)
        self.assertIs(lamp(), O)
        self.app.view.set("board")
        self.app.show_view()
        self.assertEqual([p.spec.name for p in self.app.board.parts if isinstance(p, Chip)], ["74HC00"])
        self.assertEqual(self.leds(), {"F": O})
        self.app.board_view.click(self.app.generated.inputs["A"].hole)   # flip A on the generated board
        self.assertEqual(self.leds(), {"F": I})
        self.assertIs(self.symbol("A").value, O)          # the schematic follows
        self.assertIs(lamp(), I)

    def test_too_close_is_refused_and_undone(self):
        self.app.view.set("schematic")
        self.app.show_view()
        self.place("AND", 0, 0)
        before = self.app.schematic.to_dict()
        self.app.schematic_view.tool.set("OR")
        self.app.schematic_view.place(2, 1)               # on top of the AND gate
        self.assertEqual(self.app.schematic.to_dict(), before)
        self.assertIn("Too close", self.app.status.get())

    def test_undo_and_redo(self):
        self.app.view.set("schematic")
        self.app.show_view()
        self.place("XOR", 0, 0)
        self.assertEqual(len(self.app.schematic.symbols), 1)
        self.app.undo()
        self.assertEqual(len(self.app.schematic.symbols), 0)
        self.app.redo()
        self.assertEqual(len(self.app.schematic.symbols), 1)

    def test_expression_becomes_the_circuit(self):
        panel = self.app.expression_panel
        panel.set("S = A ⊕ B; C = AB")
        self.assertIn("Read as: S = (A ⊕ B)", panel.message.cget("text"))
        self.assertEqual(len(panel.table.tree.get_children()), 4)
        panel._use()
        self.assertEqual((self.app.master, self.app.view.get()), ("schematic", "schematic"))
        self.app.toggle_input(self.symbol("A").id)
        self.app.update_panels()
        rows = panel.table.tree.get_children()
        highlighted = [i for i, item in enumerate(rows) if "now" in panel.table.tree.item(item, "tags")]
        self.assertEqual(highlighted, [2])                # A=1, B=0
        self.app.view.set("board")
        self.app.show_view()
        self.assertEqual(self.leds(), {"S": I, "C": O})

    def test_expression_errors_are_marked(self):
        panel = self.app.expression_panel
        panel.set("F = A + * B")
        self.assertIn("found '*'", panel.message.cget("text"))
        self.assertEqual(panel.text.tag_ranges("error")[0].string, "1.8")

    def test_from_circuit(self):
        self.build_half_adder()
        self.app.expression_panel._from_circuit()
        self.assertEqual(self.app.expression_panel.get(), "F = A ⊕ B\nG = A·B")

    def test_gate_selection_and_truth_table(self):
        self.build_half_adder()
        chip = self.app.board.part_at("f15")
        self.app.select_board_pin(chip, 3)
        info = self.app.gate_info()
        self.assertEqual((info.gate.name, info.input_names[0]), ("AND", "1A (pin 1)"))
        self.app.select_board_pin(chip, 14)
        self.assertEqual(self.app.gate_info().rows[13][1], "VCC")
        self.app.select_board_pin(chip, 3)
        self.app.view.set("schematic")
        self.app.show_view()                              # the same gate is selected in the schematic
        info = self.app.gate_info()
        self.assertEqual(info.gate.name, "AND")
        self.assertIn("74HC08 at column 15", info.title)

    def test_selection_follows_to_a_generated_board(self):
        self.app.expression_panel.set("F = AB + C")
        self.app.expression_panel._use()
        gate = next(s.id for s in self.app.schematic.symbols.values() if s.kind == "gate" and s.gate.name == "OR")
        self.app.select_symbol(gate)                       # before the board has been built
        self.app.view.set("board")
        self.app.show_view()
        self.app.update_panels()
        info = self.app.gate_info()
        self.assertIsNotNone(info)
        self.assertIn("74HC32", info.title)

    def test_latch_keeps_its_state_between_the_views(self):
        self.app.expression_panel.set("Q = (R + Qn)'; Qn = (S + Q)'")
        self.app.expression_panel._use()
        q = lambda: self.app.value_of(self.app.schematic.sources[Port(self.symbol("Q").id, "in1")])
        self.assertIs(q(), Logic.X)                       # power-up state
        self.app.toggle_input(self.symbol("S").id)
        self.app.toggle_input(self.symbol("S").id)        # set, then hold
        self.assertIs(q(), I)
        self.app.view.set("board")
        self.app.show_view()                              # the generated board starts in that state
        self.assertEqual(self.leds(), {"Q": I, "Qn": O})
        self.assertTrue(self.app.board_edit(lambda b: b.place(Wire("c28", "c29"))))   # the board takes over
        self.assertIs(q(), I)
        with mock.patch("tkinter.messagebox.askokcancel", return_value=True):
            self.place("input", -30, -30)                 # and the schematic takes over again
        self.assertEqual(self.app.master, "schematic")
        self.assertIs(q(), I)

    def test_moved_symbols_stay_when_the_board_changes(self):
        self.build_half_adder()
        xor = next(s for s in self.app.schematic.symbols.values() if s.label == "XOR")
        self.app.schematic_view.move({xor.id}, 0, -6)
        where = (self.app.schematic.symbols[xor.id].x, self.app.schematic.symbols[xor.id].y)
        self.board_tool("led", "i7", "B-12")             # a board change re-extracts the schematic
        self.assertEqual((self.app.schematic.symbols[xor.id].x, self.app.schematic.symbols[xor.id].y), where)

    def test_save_and_open(self):
        self.app.expression_panel.set("F = (A + B)'")
        self.app.expression_panel._use()
        saved = self.app.schematic.to_dict()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nor.json")
            with mock.patch("tkinter.filedialog.asksaveasfilename", return_value=path):
                self.app.save_schematic()
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), saved)
            with mock.patch("tkinter.messagebox.askokcancel", return_value=True):
                self.app.new_schematic()
            self.assertEqual(self.app.schematic.symbols, {})
            with mock.patch("tkinter.filedialog.askopenfilename", return_value=path):
                self.app.open_schematic()
        self.assertEqual(self.app.schematic.to_dict(), saved)

    def test_resize_and_clear(self):
        self.build_half_adder()
        self.app.board_view.size.set("Full (63)")
        self.app.board_view._resize()
        self.assertEqual(self.app.board.columns, 63)
        with mock.patch("tkinter.messagebox.askokcancel", return_value=True):
            self.app.clear_board()
        self.assertEqual(len(self.app.board.parts), 1)    # just the power supply
        self.assertEqual(self.app.schematic.symbols, {})

    def test_views_draw(self):
        self.build_half_adder()
        for view in ("board", "schematic"):
            self.app.view.set(view)
            self.app.show_view()
            v = self.app.board_view if view == "board" else self.app.schematic_view
            v.redraw()
            self.assertGreater(len(v.canvas.find_all()), 20)
        for style in ("ANSI", "IEC"):
            self.app.schematic_view.style.set(style)
            self.app.schematic_view.redraw()


if __name__ == "__main__":
    unittest.main()
