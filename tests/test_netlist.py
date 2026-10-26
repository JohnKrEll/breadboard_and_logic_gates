import random
import unittest

from breadboard.expr import evaluate, parse, to_text
from breadboard.logic import XOR, Logic
from breadboard.netlist import MAX_INPUTS, Netlist

from tests.helpers import EXAMPLES, LATCH, named_table, random_expr

O, I, X = Logic.ZERO, Logic.ONE, Logic.X


def compile(text):
    return Netlist.from_program(parse(text))


class Netlists(unittest.TestCase):
    def test_circuit_matches_direct_evaluation(self):
        rng = random.Random(2)
        for _ in range(300):
            e = random_expr(rng, 4)
            program = parse("F = " + to_text(e))
            for values, outs in Netlist.from_program(program).truth_table():
                env = dict(zip(program.inputs, values))
                self.assertEqual(outs, (evaluate(e, env),), to_text(e))

    def test_shared_subexpressions(self):
        self.assertEqual([g.gate.name for g in compile("F = AB + AB").gates], ["AND", "OR", "BUF"])

    def test_full_adder(self):
        n = compile("S = A ⊕ B ⊕ Cin; Cout = AB + Cin(A ⊕ B)")
        self.assertEqual(n.inputs, ["A", "B", "Cin"])
        self.assertEqual(sum(g.gate is XOR for g in n.gates), 2)       # A ⊕ B is shared
        for values, (s, cout) in n.truth_table():
            total = sum(v is I for v in values)
            self.assertEqual((s, cout), (Logic.of(total % 2 == 1), Logic.of(total >= 2)))

    def test_feedback_sr_latch(self):
        n = compile(LATCH)
        self.assertTrue(n.has_feedback())
        self.assertFalse(compile("F = A + B").has_feedback())
        self.assertEqual(n.inputs, ["R", "S"])
        table = dict(n.truth_table())
        self.assertEqual(table[(O, O)], (X, X))          # hold: depends on the previous state
        self.assertEqual(table[(O, I)], (I, O))          # S=1: set
        self.assertEqual(table[(I, O)], (O, I))          # R=1: reset
        self.assertEqual(table[(I, I)], (O, O))

    def test_constant_and_alias_outputs(self):
        self.assertEqual(dict(compile("F = 1; G = A; H = G'").truth_table()),
                         {(O,): (I, O, I), (I,): (I, I, O)})

    def test_too_many_inputs(self):
        names = "ABCDEGHJK"[:MAX_INPUTS + 1]
        with self.assertRaises(ValueError):
            compile("F = " + " + ".join(names)).truth_table()


class Fusing(unittest.TestCase):
    def test_not_folds_into_nand_and_nor(self):
        self.assertEqual(sorted(compile(LATCH).fused().gate_counts().items()), [("NOR", 2)])
        self.assertEqual(sorted(compile("F = (AB)'").fused().gate_counts().items()), [("NAND", 1)])

    def test_not_kept_when_the_inner_gate_is_used_elsewhere(self):
        self.assertEqual(sorted(compile("F = AB; G = (AB)'").fused().gate_counts().items()),
                         [("AND", 1), ("NOT", 1)])

    def test_truth_table_unchanged(self):
        rng = random.Random(3)
        texts = EXAMPLES + [f"F = {to_text(random_expr(rng, 4))}; G = {to_text(random_expr(rng, 3))}"
                            for _ in range(150)]
        for text in texts:
            with self.subTest(text=text):
                n = compile(text)
                self.assertEqual(named_table(n.fused()), named_table(n))


if __name__ == "__main__":
    unittest.main()
