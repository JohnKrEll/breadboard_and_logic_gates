import random
import unittest

from breadboard.derive import derive, pretty
from breadboard.expr import parse, to_text
from breadboard.extract import extract
from breadboard.logic import AND, NAND, NOT
from breadboard.netlist import Netlist
from breadboard.schematic import Port, Schematic

from tests.helpers import EXAMPLES, LATCH, named_table, random_expr
from tests.test_board import half_adder


def schematic_of(text):
    return Schematic.from_netlist(Netlist.from_program(parse(text)).fused())


class Pretty(unittest.TestCase):
    def test_round_trip(self):
        rng = random.Random(5)
        for _ in range(500):
            e = random_expr(rng, 5)
            self.assertEqual(parse("F = " + pretty(e)).equations[0].expr, e, pretty(e))

    def test_minimal_parentheses(self):
        self.assertEqual(pretty(parse("A + B·C'").equations[0].expr), "A + B·C'")
        self.assertEqual(pretty(parse("(A + B)(C + D)'").equations[0].expr), "(A + B)·(C + D)'")
        self.assertEqual(pretty(parse("A + (B + C)").equations[0].expr), "A + (B + C)")


class Derive(unittest.TestCase):
    def test_parses_back_to_the_same_circuit(self):
        rng = random.Random(6)
        texts = EXAMPLES + [f"F = {to_text(random_expr(rng, 4))}" for _ in range(150)]
        for text in texts:
            with self.subTest(text=text):
                netlist = schematic_of(text).to_netlist()
                self.assertEqual(named_table(Netlist.from_program(parse(derive(netlist)))), named_table(netlist))

    def test_hand_built_board(self):
        bb, *_ = half_adder()
        self.assertEqual(derive(extract(bb).schematic.to_netlist()), "F = A ⊕ B\nG = A·B")

    def test_feedback(self):
        self.assertEqual(derive(schematic_of(LATCH).to_netlist()), "Q = (R + Qn)'\nQn = (S + Q)'")
        sch = Schematic()                                             # a ring with no output on it
        en, f = sch.add("input", name="En"), sch.add("output")
        g1, g2, g3 = sch.add("gate", gate=NAND), sch.add("gate", gate=NOT), sch.add("gate", gate=AND)
        sch.connect(Port(en.id, "out"), Port(g1.id, "in1"))
        sch.connect(Port(g1.id, "out"), Port(g2.id, "in1"))
        sch.connect(Port(g2.id, "out"), Port(g1.id, "in2"))
        sch.connect(Port(g2.id, "out"), Port(g3.id, "in1"))
        sch.connect(Port(en.id, "out"), Port(g3.id, "in2"))
        sch.connect(Port(g3.id, "out"), Port(f.id, "in1"))
        self.assertEqual(derive(sch.to_netlist()), "F = T1·En\nT1 = (En·T1)''")

    def test_unconnected_input_raises(self):
        sch = Schematic()
        g, f = sch.add("gate", gate=AND), sch.add("output")
        sch.connect(Port(g.id, "out"), Port(f.id, "in1"))
        with self.assertRaises(ValueError) as caught:
            derive(sch.to_netlist())
        self.assertIn("g1.in1 is not connected", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
