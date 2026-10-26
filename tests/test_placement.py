import random
import unittest

from breadboard.expr import parse, to_text
from breadboard.netlist import Netlist
from breadboard.placement import auto_place
from breadboard.schematic import Schematic

from tests.helpers import EXAMPLES, LATCH, random_expr


def schematic_of(text):
    return Schematic.from_netlist(Netlist.from_program(parse(text)).fused())


class Placement(unittest.TestCase):
    def check(self, sch):
        xs = {s.kind: set() for s in sch.symbols.values()}
        for s in sch.symbols.values():
            xs[s.kind].add(s.x)
            self.assertTrue(sch.fits(s.id, s.x, s.y), f"{s.id} is too close to another symbol")
        self.assertEqual(xs.get("input", {0}), {0})                  # inputs in the first column
        if "output" in xs:
            self.assertEqual(len(xs["output"]), 1)                    # outputs in the last column
            self.assertGreater(min(xs["output"]), max(s.x for s in sch.symbols.values() if s.kind != "output"))
        for inp, out in sch.sources.items():                          # wires go left to right,
            if (out.symbol, inp.symbol) not in feedback(sch):          # except feedback
                self.assertLess(sch.symbols[out.symbol].x, sch.symbols[inp.symbol].x)

    def test_examples_and_random(self):
        rng = random.Random(5)
        texts = EXAMPLES + [LATCH] + [f"F = {to_text(random_expr(rng, 4))}" for _ in range(80)]
        for text in texts:
            with self.subTest(text=text):
                self.check(schematic_of(text))

    def test_fixed_symbols_stay(self):
        sch = schematic_of(EXAMPLES[2])
        sch.symbols["g1"].x, sch.symbols["g1"].y = 60, 40
        auto_place(sch, frozenset({"g1"}))
        self.assertEqual((sch.symbols["g1"].x, sch.symbols["g1"].y), (60, 40))
        for s in sch.symbols.values():
            self.assertTrue(sch.fits(s.id, s.x, s.y))


def feedback(sch):
    """(source symbol, target symbol) pairs on a cycle."""
    succ = {}
    for inp, out in sch.sources.items():
        succ.setdefault(out.symbol, set()).add(inp.symbol)

    def reaches(a, b, seen=None):
        seen = seen or set()
        if a == b:
            return True
        seen.add(a)
        return any(reaches(n, b, seen) for n in succ.get(a, ()) if n not in seen)

    return {(o.symbol, i.symbol) for i, o in sch.sources.items() if reaches(i.symbol, o.symbol)}


if __name__ == "__main__":
    unittest.main()
