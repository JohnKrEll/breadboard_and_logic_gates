import unittest

from breadboard.board import Breadboard, Chip, Led, PowerSupply, Resistor, Wire
from breadboard.chips import CHIPS
from breadboard.expr import parse
from breadboard.extract import extract
from breadboard.layout import layout
from breadboard.logic import Logic
from breadboard.netlist import Netlist
from breadboard.schematic import Port

from tests.helpers import EXAMPLES, LATCH, named_table
from tests.test_board import half_adder

O, I = Logic.ZERO, Logic.ONE


class Extraction(unittest.TestCase):
    def test_hand_built_half_adder(self):
        bb, A, B, s, c, _ = half_adder()
        result = extract(bb)
        sch = result.schematic
        self.assertEqual(result.problems, [])
        names = sorted((x.kind, x.label) for x in sch.symbols.values())
        self.assertEqual(names, [("gate", "AND"), ("gate", "XOR"), ("input", "A"), ("input", "B"),
                                 ("output", "F"), ("output", "G")])
        self.assertEqual(dict(sch.to_netlist().truth_table()),
                         {(O, O): (O, O), (O, I): (I, O), (I, O): (I, O), (I, I): (O, I)})
        bb.set(A, I)
        bb.set(B, I)
        for x in sch.symbols.values():                               # live values come from the board
            if x.kind == "output":
                src = sch.sources[Port(x.id, "in1")]
                self.assertIs(result.live[src].value, bb.led(result.parts[x.id]))
        chip, index = next(iter(result.gates.values()))
        self.assertIsInstance(chip, Chip)

    def test_generated_boards_extract_back(self):
        for text in EXAMPLES[:5] + [LATCH]:
            with self.subTest(text=text):
                netlist = Netlist.from_program(parse(text)).fused()
                result = extract(layout(netlist).board)
                self.assertEqual(result.problems, [])
                self.assertEqual(named_table(result.schematic.to_netlist()), named_table(netlist))

    def test_positions_and_names_survive_rewiring(self):
        bb, *_ = half_adder()
        first = extract(bb).schematic
        moved = next(iter(first.symbols.values()))
        moved.x += 7                                                 # the user moved a symbol
        bb.place(Led("i7", "B-9"))                                   # a second LED on the sum
        second = extract(bb, previous=first).schematic
        for id, s in first.symbols.items():
            self.assertEqual((second.symbols[id].x, second.symbols[id].y, second.symbols[id].name),
                             (s.x, s.y, s.name))
        self.assertEqual(len(second.symbols), len(first.symbols) + 1)

    def test_labels_name_symbols(self):
        bb, A, B, s, c, _ = half_adder()
        A.label, s.label = "X1", "Sum"
        names = {x.name for x in extract(bb).schematic.symbols.values() if x.name}
        self.assertTrue({"X1", "Sum"} <= names)

    def test_pull_up_becomes_a_constant(self):
        bb = Breadboard()
        bb.place(PowerSupply("T+1", "T-1"))
        bb.place(Chip(CHIPS["7404"], 5))
        bb.place(Wire("a5", "T+2"))
        bb.place(Wire("j11", "T-2"))
        bb.place(Resistor("j5", "T+20"))                             # inverter input pulled up
        bb.place(Led("g6", "T-6"))
        kinds = sorted((s.kind, s.name) for s in extract(bb).schematic.symbols.values())
        self.assertEqual(kinds, [("const", "1"), ("gate", ""), ("output", "F")])

    def test_short_is_reported(self):
        bb, A, *_ = half_adder()
        bb.place(Wire("i5", "i6"))                                   # both switches on one net
        self.assertTrue(extract(bb).problems)


if __name__ == "__main__":
    unittest.main()
