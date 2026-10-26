import random
import unittest

from breadboard.expr import parse, to_text
from breadboard.logic import AND, NAND, Logic
from breadboard.netlist import Netlist
from breadboard.schematic import Port, Schematic

from tests.helpers import EXAMPLES, LATCH, named_table, random_expr

O, I, X = Logic.ZERO, Logic.ONE, Logic.X


def schematic_of(text):
    return Schematic.from_netlist(Netlist.from_program(parse(text)).fused())


class Editing(unittest.TestCase):
    def test_build_by_hand(self):
        sch = Schematic()
        a, b = sch.add("input"), sch.add("input")
        g = sch.add("gate", gate=NAND)
        f = sch.add("output")
        self.assertEqual((a.name, b.name, f.name), ("A", "B", "F"))
        sch.connect(Port(a.id, "out"), Port(g.id, "in1"))
        sch.connect(Port(g.id, "in2"), Port(b.id, "out"))            # either order
        sch.connect(Port(g.id, "out"), Port(f.id, "in1"))
        self.assertEqual(dict(sch.to_netlist().truth_table()),
                         {(O, O): (I,), (O, I): (I,), (I, O): (I,), (I, I): (O,)})
        self.assertEqual(sch.problems(), [])

    def test_rules(self):
        sch = Schematic()
        a, b = sch.add("input"), sch.add("input")
        g = sch.add("gate", gate=AND)
        with self.assertRaises(ValueError):
            sch.connect(Port(a.id, "out"), Port(b.id, "out"))        # two outputs
        with self.assertRaises(ValueError):
            sch.connect(Port(g.id, "in1"), Port(g.id, "in2"))        # two inputs
        with self.assertRaises(ValueError):
            sch.connect(Port(a.id, "out"), Port(g.id, "in3"))        # no such pin
        sch.connect(Port(a.id, "out"), Port(g.id, "in1"))
        self.assertEqual(sch.connect(Port(b.id, "out"), Port(g.id, "in1")), Port(a.id, "out"))
        with self.assertRaises(ValueError):
            sch.rename(b.id, "A")                                    # names are unique
        with self.assertRaises(ValueError):
            sch.rename(b.id, "b")                                    # and follow the expression rules
        with self.assertRaises(ValueError):
            sch.add("const", name="2")
        sch.remove(b.id)
        self.assertEqual(sch.sources, {})

    def test_spacing(self):
        sch = Schematic()
        g1 = sch.add("gate", gate=AND, x=0, y=0)
        g2 = sch.add("gate", gate=AND, x=20, y=0)
        self.assertFalse(sch.fits(g2.id, 6, 0))                      # one free column: too close
        self.assertTrue(sch.fits(g2.id, 7, 0))                       # two free columns
        self.assertFalse(sch.fits(g2.id, 0, 5))                      # touching below
        self.assertTrue(sch.fits(g2.id, 0, 6))                       # one free row
        with self.assertRaises(ValueError):
            sch.move(g2.id, 2, 2)
        self.assertEqual((g2.x, g2.y), (20, 0))

    def test_unconnected_input_is_floating(self):
        sch = Schematic()
        a, g, f = sch.add("input"), sch.add("gate", gate=AND), sch.add("output")
        sch.connect(Port(a.id, "out"), Port(g.id, "in1"))
        sch.connect(Port(g.id, "out"), Port(f.id, "in1"))
        self.assertEqual(dict(sch.to_netlist().truth_table()), {(O,): (O,), (I,): (X,)})   # AND(0, Z) = 0
        self.assertEqual(sch.problems(), [f"AND gate {g.id}: input 2 is not connected"])

    def test_json_round_trip(self):
        sch = schematic_of(EXAMPLES[2])
        sch.symbols["in1"].value = I
        again = Schematic.from_dict(sch.to_dict())
        self.assertEqual(again.to_dict(), sch.to_dict())
        self.assertEqual(named_table(again.to_netlist()), named_table(sch.to_netlist()))
        with self.assertRaises(ValueError):
            Schematic.from_dict({"symbols": [{"id": "g1", "kind": "gate", "gate": "MAGIC", "x": 0, "y": 0}],
                                 "wires": []})

    def test_renamed_keeps_positions(self):
        sch = schematic_of("F = A + B")
        ids = {id: id.upper() for id in sch.symbols}
        moved = sch.renamed(ids)
        for id, s in sch.symbols.items():
            self.assertEqual((moved.symbols[id.upper()].x, moved.symbols[id.upper()].y), (s.x, s.y))


class Conversions(unittest.TestCase):
    def test_expression_to_schematic_keeps_the_truth_table(self):
        rng = random.Random(4)
        texts = EXAMPLES + [f"F = {to_text(random_expr(rng, 4))}; G = {to_text(random_expr(rng, 3))}"
                            for _ in range(150)]
        for text in texts:
            with self.subTest(text=text):
                original = Netlist.from_program(parse(text))
                self.assertEqual(named_table(schematic_of(text).to_netlist()), named_table(original))

    def test_latch_is_two_nor_gates(self):
        gates = sorted(s.gate.name for s in schematic_of(LATCH).symbols.values() if s.kind == "gate")
        self.assertEqual(gates, ["NOR", "NOR"])

    def test_outputs_top_to_bottom(self):
        sch = schematic_of("S = A ⊕ B; C = AB")
        order = [s.name for s in sorted((s for s in sch.symbols.values() if s.kind == "output"),
                                        key=lambda s: (s.y, s.x))]
        self.assertEqual(sch.to_netlist().outputs, order)


if __name__ == "__main__":
    unittest.main()
