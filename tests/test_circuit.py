import unittest
from itertools import product

from breadboard.circuit import Circuit, GateNode, InputNode, LedNode, ResistorHalf
from breadboard.logic import AND, NAND, NOR, NOT, OR, XOR, Logic

O, I, X, Z = Logic.ZERO, Logic.ONE, Logic.X, Logic.Z


class NetResolution(unittest.TestCase):
    """The table in design.md section 2.4."""

    def setUp(self):
        self.c = Circuit()
        self.n = self.c.net("n")

    def test_no_drivers_is_floating(self):
        self.c.settle()
        self.assertIs(self.n.value, Z)

    def test_one_driver(self):
        self.c.add(InputNode("a", self.n, I))
        self.c.settle()
        self.assertEqual((self.n.value, self.n.strong, self.n.short), (I, True, False))

    def test_drivers_that_agree(self):
        self.c.add(InputNode("a", self.n, I))
        self.c.add(InputNode("b", self.n, I))
        self.c.settle()
        self.assertEqual((self.n.value, self.n.short), (I, False))

    def test_drivers_that_disagree_short(self):
        self.c.add(InputNode("a", self.n, I))
        self.c.add(InputNode("b", self.n, O))
        self.c.settle()
        self.assertEqual((self.n.value, self.n.short), (X, True))

    def test_only_resistor_to_ground_is_weak_zero(self):
        gnd = self.c.net("gnd")
        self.c.add(InputNode("gnd", gnd, O))
        self.c.add(ResistorHalf("r", gnd, self.n))
        self.c.settle()
        self.assertEqual((self.n.value, self.n.strong), (O, False))

    def test_strong_driver_beats_resistor(self):
        gnd = self.c.net("gnd")
        self.c.add(InputNode("gnd", gnd, O))
        self.c.add(ResistorHalf("r", gnd, self.n))
        self.c.add(InputNode("a", self.n, I))
        self.c.settle()
        self.assertEqual((self.n.value, self.n.strong, self.n.short), (I, True, False))

    def test_resistor_does_not_pass_weak_values(self):
        gnd, mid = self.c.net("gnd"), self.c.net("mid")
        self.c.add(InputNode("gnd", gnd, O))
        self.c.add(ResistorHalf("r1", gnd, mid))
        self.c.add(ResistorHalf("r1 back", mid, gnd))
        self.c.add(ResistorHalf("r2", mid, self.n))
        self.c.settle()
        self.assertIs(mid.value, O)
        self.assertIs(self.n.value, Z)       # two resistors in a row don't pass a value


def full_adder():
    c = Circuit()
    a, b, cin, s, cout, t1, t2, t3 = (c.net(x) for x in "a b cin s cout t1 t2 t3".split())
    inputs = [c.add(InputNode(net.name, net)) for net in (a, b, cin)]
    c.add(GateNode("x1", XOR, [a, b], t1))
    c.add(GateNode("x2", XOR, [t1, cin], s))
    c.add(GateNode("a1", AND, [a, b], t2))
    c.add(GateNode("a2", AND, [t1, cin], t3))
    c.add(GateNode("o1", OR, [t2, t3], cout))
    return c, inputs, s, cout


class Combinational(unittest.TestCase):
    def test_full_adder(self):
        c, inputs, s, cout = full_adder()
        c.settle()
        for bits in product((0, 1), repeat=3):
            for node, bit in zip(inputs, bits):
                c.set_input(node, Logic.of(bool(bit)))
            total = sum(bits)
            with self.subTest(inputs=bits):
                self.assertIs(s.value, Logic.of(bool(total & 1)))
                self.assertIs(cout.value, Logic.of(total >= 2))

    def test_topological_seeding_evaluates_each_node_once(self):
        c, *_ = full_adder()
        calls = []
        for node in c.nodes:
            original = node.compute
            node.compute = lambda node=node, original=original: calls.append(node) or original()
        c.settle()
        self.assertCountEqual(calls, c.nodes)

    def test_unpowered_gate_outputs_z_until_powered(self):
        c = Circuit()
        vcc, gnd, a, y = (c.net(x) for x in "vcc gnd a y".split())
        power = c.add(InputNode("vcc", vcc, O))
        c.add(InputNode("gnd", gnd, O))
        c.add(InputNode("a", a, O))
        c.add(GateNode("inv", NOT, [a], y, power=(vcc, gnd)))
        c.settle()
        self.assertIs(y.value, Z)
        c.set_input(power, I)
        self.assertIs(y.value, I)

    def test_led(self):
        c = Circuit()
        anode, cathode = c.net("anode"), c.net("cathode")
        a = c.add(InputNode("a", anode, I))
        k = c.add(InputNode("k", cathode, O))
        led = c.add(LedNode("led", anode, cathode))
        c.settle()
        self.assertIs(led.value, I)
        c.set_input(a, O)
        self.assertIs(led.value, O)
        c.set_input(a, I)
        c.set_input(k, I)                    # wrong way round / no voltage across it
        self.assertIs(led.value, O)
        c.set_input(k, X)
        self.assertIs(led.value, X)


def sr_latch():
    c = Circuit()
    s, r, q, qn = (c.net(x) for x in "s r q qn".split())
    S = c.add(InputNode("S", s))
    R = c.add(InputNode("R", r))
    c.add(GateNode("nor1", NOR, [r, qn], q))
    c.add(GateNode("nor2", NOR, [s, q], qn))
    return c, S, R, q, qn


def ring_oscillator():
    c = Circuit()
    en, a, b, y, other = (c.net(x) for x in "en a b y other".split())
    EN = c.add(InputNode("EN", en, O))
    OTHER = c.add(InputNode("OTHER", other, O))
    c.add(GateNode("nand", NAND, [en, y], a))
    c.add(GateNode("inv1", NOT, [a], b))
    c.add(GateNode("inv2", NOT, [b], y))
    return c, EN, OTHER, (a, b, y)


class Feedback(unittest.TestCase):
    def test_sr_latch(self):
        c, S, R, q, qn = sr_latch()
        c.settle()
        self.assertEqual((q.value, qn.value), (X, X))   # unknown at power-up
        c.set_input(S, I)
        self.assertEqual((q.value, qn.value), (I, O))   # set
        c.set_input(S, O)
        self.assertEqual((q.value, qn.value), (I, O))   # hold
        c.set_input(R, I)
        self.assertEqual((q.value, qn.value), (O, I))   # reset
        c.set_input(R, O)
        self.assertEqual((q.value, qn.value), (O, I))   # hold
        self.assertEqual(c.oscillating, set())

    def test_ring_oscillator(self):
        c, EN, OTHER, nets = ring_oscillator()
        c.settle()
        self.assertEqual([n.value for n in nets], [I, O, I])
        self.assertEqual(c.oscillating, set())

        c.set_input(EN, I)                   # three inversions in a loop: never settles
        self.assertNotEqual(c.oscillating, set())
        self.assertIn(X, [n.value for n in nets])

        c.set_input(OTHER, I)                # an unrelated change keeps it reported
        self.assertNotEqual(c.oscillating, set())

        c.set_input(EN, O)                   # disabled: recovers
        self.assertEqual([n.value for n in nets], [I, O, I])
        self.assertEqual(c.oscillating, set())


if __name__ == "__main__":
    unittest.main()
