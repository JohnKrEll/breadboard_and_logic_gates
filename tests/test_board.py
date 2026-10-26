import unittest
from itertools import product

from breadboard.board import (Breadboard, Chip, Led, LogicInput, PowerSupply, Resistor, Wire,
                              parse_hole, strip_of)
from breadboard.chips import CHIPS, ChipSpec
from breadboard.logic import AND, NOT, Logic

O, I, X, Z = Logic.ZERO, Logic.ONE, Logic.X, Logic.Z


class Holes(unittest.TestCase):
    def test_parse_hole(self):
        self.assertEqual(parse_hole("c5"), ("c", 5))
        self.assertEqual(parse_hole("j30"), ("j", 30))
        self.assertEqual(parse_hole("T+3"), ("T+", 3))
        self.assertEqual(parse_hole("B-12"), ("B-", 12))
        for bad in ("", "k5", "a", "T+", "T+x", "5a", "a-1", "T*3"):
            with self.subTest(hole=bad), self.assertRaises(ValueError):
                parse_hole(bad)

    def test_strip_of(self):
        self.assertEqual(strip_of("a5"), "top5")
        self.assertEqual(strip_of("e5"), "top5")
        self.assertEqual(strip_of("f5"), "bot5")
        self.assertEqual(strip_of("j5"), "bot5")
        self.assertEqual(strip_of("T+3"), "T+")
        self.assertEqual(strip_of("B-30"), "B-")


class Chips(unittest.TestCase):
    def test_pin_mapping(self):
        chip = Chip(CHIPS["7408"], 5)
        self.assertEqual(chip.pin_hole(1), "f5")
        self.assertEqual(chip.pin_hole(7), "f11")
        self.assertEqual(chip.pin_hole(8), "e11")
        self.assertEqual(chip.pin_hole(14), "e5")

    def test_pin_names_match_the_datasheets(self):
        self.assertEqual({p: CHIPS["7400"].pin_names()[p] for p in (1, 2, 3, 7, 14)},
                         {1: "1A", 2: "1B", 3: "1Y", 7: "GND", 14: "VCC"})
        self.assertEqual({p: CHIPS["7402"].pin_names()[p] for p in (1, 2, 3, 13)},
                         {1: "1Y", 2: "1A", 3: "1B", 13: "4Y"})
        self.assertEqual({p: CHIPS["7404"].pin_names()[p] for p in (1, 2, 8, 9)},
                         {1: "1A", 2: "1Y", 8: "4Y", 9: "4A"})
        self.assertEqual((CHIPS["7408"].gate_at(5), CHIPS["7408"].gate_at(11), CHIPS["7408"].gate_at(7)),
                         (1, 3, None))

    def test_spec_checks_arity_and_pins(self):
        with self.assertRaises(ValueError):
            ChipSpec("bad", vcc=14, gnd=7, gates=((AND, (1,), 2),))
        with self.assertRaises(ValueError):
            ChipSpec("bad", vcc=14, gnd=7, gates=((NOT, (1,), 15),))

    def test_every_chip_works_on_the_board(self):
        # The free hole at the far end of a pin's strip: e -> a, f -> j.
        free = lambda hole: {"e": "a", "f": "j"}[hole[0]] + hole[1:]
        for key, spec in CHIPS.items():
            bb = Breadboard()
            bb.place(PowerSupply("T+1", "T-1"))
            chip = bb.place(Chip(spec, 5))
            bb.place(Wire(free(chip.pin_hole(spec.vcc)), "T+2"))
            bb.place(Wire(free(chip.pin_hole(spec.gnd)), "T-2"))
            for gate, ins, out in spec.gates:
                switches = [bb.place(LogicInput(free(chip.pin_hole(p)))) for p in ins]
                for values in product((O, I), repeat=len(ins)):
                    for switch, value in zip(switches, values):
                        bb.set(switch, value)
                    with self.subTest(chip=key, output_pin=out, inputs=values):
                        self.assertIs(bb.net_at(chip.pin_hole(out)).value,
                                      gate.evaluate(*values))


class Placing(unittest.TestCase):
    def test_hole_already_taken(self):
        bb = Breadboard()
        bb.place(Wire("a1", "a2"))
        with self.assertRaises(ValueError):
            bb.place(Wire("a1", "a3"))
        self.assertEqual(len(bb.parts), 1)   # the failed part was not added

    def test_chip_over_a_taken_hole(self):
        bb = Breadboard()
        bb.place(Wire("e8", "a20"))
        with self.assertRaises(ValueError):
            bb.place(Chip(CHIPS["7400"], 5))  # needs e5..e11

    def test_off_the_board(self):
        bb = Breadboard()
        with self.assertRaises(ValueError):
            bb.place(Wire("a1", "a31"))
        with self.assertRaises(ValueError):
            bb.place(Chip(CHIPS["7400"], 25))  # pins would reach column 31
        with self.assertRaises(ValueError):
            bb.place(Wire("a1", "z1"))

    def test_same_hole_twice(self):
        with self.assertRaises(ValueError):
            Breadboard().place(Wire("a1", "a1"))

    def test_logic_input_only_takes_0_or_1(self):
        bb = Breadboard()
        switch = bb.place(LogicInput("a1"))
        with self.assertRaises(ValueError):
            bb.set(switch, X)

    def test_uids_and_resize(self):
        bb = Breadboard()
        a, b = bb.place(Wire("a1", "a2")), bb.place(LogicInput("c25", label="A"))
        self.assertEqual((a.uid, b.uid, b.label), (1, 2, "A"))
        bb.remove(a)
        self.assertEqual(bb.place(Wire("a3", "a4")).uid, 3)          # uids are never reused
        with self.assertRaises(ValueError):
            bb.resize(20)                                            # the switch is in column 25
        self.assertEqual(bb.columns, 30)
        bb.resize(63)
        bb.place(Wire("a60", "a61"))
        self.assertEqual(bb.columns, 63)

    def test_unused_hole_has_no_net(self):
        bb = Breadboard()
        bb.place(LogicInput("a1"))
        self.assertIsNone(bb.net_at("a2"))
        self.assertIs(bb.net_at("e1").value, O)   # same strip as a1


def half_adder(power_and=True):
    """The worked example in design.md section 5."""
    bb = Breadboard()
    bb.place(PowerSupply("T+1", "T-1"))
    bb.place(Wire("T+3", "B+1"))                 # feed the bottom rails
    bb.place(Wire("T-3", "B-1"))

    bb.place(Chip(CHIPS["7486"], 5))
    bb.place(Wire("a5", "T+2"))                  # pin 14 (e5) -> VCC
    bb.place(Wire("j11", "B-2"))                 # pin 7 (f11) -> GND
    bb.place(Chip(CHIPS["7408"], 15))
    vcc = bb.place(Wire("a15", "T+5")) if power_and else None
    bb.place(Wire("j21", "B-6"))

    A = bb.place(LogicInput("j5"))               # XOR pin 1
    B = bb.place(LogicInput("j6"))               # XOR pin 2
    bb.place(Wire("h5", "h15"))                  # A -> AND pin 1
    bb.place(Wire("h6", "h16"))                  # B -> AND pin 2

    s = bb.place(Led("g7", "B-5"))               # XOR pin 3; cathode straight to GND
    bb.place(Wire("g17", "g25"))                 # AND pin 3, moved to free space
    c = bb.place(Led("h25", "h26"))
    bb.place(Resistor("i26", "B-8"))             # LED -> resistor -> GND
    return bb, A, B, s, c, vcc


class HalfAdder(unittest.TestCase):
    def test_truth_table(self):
        bb, A, B, s, c, _ = half_adder()
        for a, b in product((O, I), repeat=2):
            bb.set(A, a)
            bb.set(B, b)
            with self.subTest(a=a, b=b):
                self.assertIs(bb.led(s), Logic.of((a is I) != (b is I)))
                self.assertIs(bb.led(c), Logic.of(a is I and b is I))
                self.assertEqual(bb.diagnose(), [])

    def test_toggle(self):
        bb, A, B, s, c, _ = half_adder()
        bb.toggle(A)
        self.assertEqual((bb.led(s), bb.led(c)), (I, O))
        bb.toggle(B)
        self.assertEqual((bb.led(s), bb.led(c)), (O, I))
        bb.toggle(A)
        self.assertEqual((bb.led(s), bb.led(c)), (I, O))

    def test_unpowered_chip(self):
        bb, A, B, s, c, _ = half_adder(power_and=False)
        bb.set(A, I)
        bb.set(B, I)
        self.assertIs(bb.led(c), O)
        self.assertEqual(bb.diagnose(), ["74HC08 at column 15 is not powered"])

    def test_removing_the_power_wire(self):
        bb, A, B, s, c, vcc = half_adder()
        bb.set(A, I)
        bb.set(B, I)
        self.assertIs(bb.led(c), I)
        bb.remove(vcc)
        self.assertIs(bb.led(c), O)
        self.assertEqual(bb.diagnose(), ["74HC08 at column 15 is not powered"])

    def test_floating_input(self):
        bb, A, B, s, c, _ = half_adder()
        bb.remove(bb.part_at("h16"))             # unplug B from the AND gate
        bb.set(A, I)
        self.assertIs(bb.led(c), X)
        self.assertEqual(bb.diagnose(), ["74HC08 at column 15: input pin 2 is floating"])

    def test_short(self):
        bb, *_ = half_adder()
        bb.place(Wire("T+10", "T-10"))
        self.assertTrue(any(p.startswith("short circuit") for p in bb.diagnose()), bb.diagnose())


def powered_board(*chips):
    """A board with power and the given (spec key, column) chips wired to the top rails."""
    bb = Breadboard()
    bb.place(PowerSupply("T+1", "T-1"))
    for i, (key, column) in enumerate(chips):
        chip = bb.place(Chip(CHIPS[key], column))
        bb.place(Wire("a" + chip.pin_hole(14)[1:], f"T+{2 + i}"))
        bb.place(Wire("j" + chip.pin_hole(7)[1:], f"T-{2 + i}"))
    return bb


class Feedback(unittest.TestCase):
    def latch(self):
        # 74HC02: 1Y=Q (f5), 1A=R (f6), 1B (f7) <- Qn; 2Y=Qn (f8), 2A=S (f9), 2B (f10) <- Q
        bb = powered_board(("7402", 5))
        R = bb.place(LogicInput("j6"))
        S = bb.place(LogicInput("j9"))
        bb.place(Wire("h8", "h7"))
        bb.place(Wire("i5", "i10"))
        q = bb.place(Led("g5", "T-5"))
        return bb, S, R, q

    def test_latch_survives_rewiring(self):
        bb, S, R, q = self.latch()
        self.assertIs(bb.led(q), X)             # power-up state is unknown
        bb.set(S, I)
        bb.set(S, O)
        self.assertIs(bb.led(q), I)
        bb.place(Led("g8", "T-6"))              # rewiring rebuilds the circuit...
        self.assertIs(bb.led(q), I)             # ...but the latch keeps its state
        bb.set(R, I)
        self.assertIs(bb.led(q), O)

    def test_oscillation_is_reported_and_survives_rewiring(self):
        # NAND (7400 at 15) with EN on pin 1, then two inverters (7404 at 5), back to pin 2.
        bb = powered_board(("7404", 5), ("7400", 15))
        EN = bb.place(LogicInput("j15"))
        bb.place(Wire("h17", "h5"))              # NAND out -> inverter 1 in
        bb.place(Wire("h6", "h7"))               # inverter 1 out -> inverter 2 in
        bb.place(Wire("i8", "i16"))              # inverter 2 out -> NAND pin 2
        self.assertEqual(bb.diagnose(), [])
        bb.set(EN, I)
        self.assertTrue(any(p.startswith("oscillation") for p in bb.diagnose()), bb.diagnose())
        bb.place(Led("g8", "T-9"))               # unrelated rebuild
        self.assertTrue(any(p.startswith("oscillation") for p in bb.diagnose()), bb.diagnose())
        bb.set(EN, O)
        self.assertEqual(bb.diagnose(), [])


class Resistors(unittest.TestCase):
    def test_pull_up_is_overridden_by_a_real_output(self):
        bb = powered_board(("7404", 5))         # inverter: in f5, out f6
        bb.place(Resistor("j5", "T+20"))         # pull the input up
        out = lambda: bb.net_at("f6").value      # look up again: placing a part rebuilds the nets
        self.assertIs(out(), O)
        switch = bb.place(LogicInput("i5", O))   # a real 0 beats the pull-up
        self.assertIs(out(), I)
        self.assertFalse(bb.net_at("f5").short)
        bb.set(switch, I)
        self.assertIs(out(), O)


if __name__ == "__main__":
    unittest.main()
