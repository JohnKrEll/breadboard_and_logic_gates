import random
import unittest

from breadboard.expr import parse, to_text
from breadboard.netlist import Netlist
from breadboard.routing import route
from breadboard.schematic import Schematic

from tests.helpers import EXAMPLES, LATCH, random_expr


def schematic_of(text):
    return Schematic.from_netlist(Netlist.from_program(parse(text)).fused())


class Routing(unittest.TestCase):
    def check(self, sch):
        wires, junctions = route(sch)
        self.assertEqual(len(wires), len(sch.sources))
        self.assertTrue(all(w.routed for w in wires), [str(w.target) for w in wires if not w.routed])
        bodies = {}
        for s in sch.symbols.values():
            w, h = s.size()
            for x in range(s.x, s.x + w + 1):
                for y in range(s.y, s.y + h + 1):
                    bodies[(x, y)] = s.id
        nets_at = {}
        for w in wires:
            pts = w.points
            self.assertEqual(pts[-1], sch.port_xy(w.target))
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                self.assertTrue(ax == bx or ay == by, pts)            # orthogonal
                n = max(abs(bx - ax), abs(by - ay))
                for i in range(n + 1):
                    cell = (ax + (bx > ax) * i - (bx < ax) * i, ay + (by > ay) * i - (by < ay) * i)
                    if cell in bodies and cell not in (sch.port_xy(w.source), sch.port_xy(w.target)):
                        self.fail(f"{w.source}->{w.target} goes through {bodies[cell]} at {cell}")
                    nets_at.setdefault((cell, "h" if ay == by else "v"), set()).add(w.source)
        for (cell, _), nets in nets_at.items():
            self.assertEqual(len(nets), 1, f"two nets overlap at {cell}")

    def test_examples(self):
        for text in EXAMPLES + [LATCH]:
            with self.subTest(text=text):
                self.check(schematic_of(text))

    def test_random(self):
        rng = random.Random(7)
        for _ in range(40):
            text = f"F = {to_text(random_expr(rng, 4))}; G = {to_text(random_expr(rng, 3))}"
            with self.subTest(text=text):
                self.check(schematic_of(text))

    def test_moved_symbols(self):
        rng = random.Random(8)
        for i in range(200):
            sch = schematic_of(EXAMPLES[i % 5])
            for s in list(sch.symbols.values()):                     # the user shuffles things around
                x, y = s.x + rng.randint(-3, 3), s.y + rng.randint(-3, 3)
                if sch.fits(s.id, x, y):
                    sch.move(s.id, x, y)
            with self.subTest(i=i):
                self.check(sch)

    def test_branches_get_junction_dots(self):
        _, junctions = route(schematic_of("F = AB + AC"))            # A feeds two gates
        self.assertTrue(junctions)


if __name__ == "__main__":
    unittest.main()
