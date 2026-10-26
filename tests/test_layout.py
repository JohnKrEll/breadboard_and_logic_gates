import random
import unittest

from breadboard.board import Chip
from breadboard.expr import parse, to_text
from breadboard.layout import chips_needed, layout
from breadboard.netlist import Netlist

from tests.helpers import EXAMPLES, LATCH, random_expr


class Layouts(unittest.TestCase):
    def check(self, netlist, text=""):
        result = layout(netlist)
        board = result.board
        for values, outs in netlist.truth_table():
            for name, value in zip(netlist.inputs, values):
                board.set(result.inputs[name], value)
            got = tuple(board.led(result.leds[name]) for name in netlist.outputs)
            self.assertEqual(got, outs, f"{text} {values}")
        self.assertEqual(board.diagnose(), [], text)
        return result

    def test_examples(self):
        for text in EXAMPLES + ["F = A'", "F = A", "F = 1; G = 0", "F = A·1 + B·0", "F = A'B'C' + ABC"]:
            with self.subTest(text=text):
                self.check(Netlist.from_program(parse(text)), text)

    def test_labels_and_gate_mapping(self):
        n = Netlist.from_program(parse("S = A ⊕ B; C = AB"))
        result = self.check(n)
        self.assertEqual({p.label for p in result.inputs.values()}, {"A", "B"})
        self.assertEqual({p.label for p in result.leds.values()}, {"S", "C"})
        for signal, (chip, index) in result.gates.items():
            gate = next(g for g in n.gates if g.output == signal).gate
            self.assertIs(chip.spec.gates[index][0], gate)

    def test_fused_latch_is_one_74hc02(self):
        result = self.check(Netlist.from_program(parse(LATCH)).fused())
        self.assertEqual([p.spec.name for p in result.board.parts if isinstance(p, Chip)], ["74HC02"])

    def test_fan_out_beyond_one_strip(self):
        result = self.check(Netlist.from_program(parse("F = A·A·A·A·A·A·A·A·A + A'")))   # A feeds 11 inputs
        self.assertGreater(len(result.board.parts), 20)

    def test_many_chips_grow_the_board(self):
        result = self.check(Netlist.from_program(parse(EXAMPLES[4])))
        self.assertGreater(result.board.columns, 30)

    def test_random(self):
        rng = random.Random(3)
        for _ in range(60):
            text = f"F = {to_text(random_expr(rng, 4))}; G = {to_text(random_expr(rng, 3))}"
            with self.subTest(text=text):
                self.check(Netlist.from_program(parse(text)), text)

    def test_chips_needed(self):
        n = Netlist.from_program(parse("S = A ⊕ B ⊕ Cin; Cout = AB + Cin(A ⊕ B)"))
        self.assertEqual(dict(chips_needed(n)), {"74HC86": 1, "74HC08": 1, "74HC32": 1})


if __name__ == "__main__":
    unittest.main()
