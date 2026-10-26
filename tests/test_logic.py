import unittest
from itertools import product

from breadboard.logic import AND, AND3, BUF, GATES, NAND, NOR, NOT, OR, XOR, Logic, truth_table

O, I, X, Z = Logic.ZERO, Logic.ONE, Logic.X, Logic.Z


class TruthTables(unittest.TestCase):
    def check(self, gate, expected):
        for bits in product((False, True), repeat=gate.arity):
            with self.subTest(gate=gate.name, inputs=bits):
                self.assertIs(gate.evaluate(*map(Logic.of, bits)), Logic.of(expected(*bits)))

    def test_two_input_gates(self):
        self.check(AND, lambda a, b: a and b)
        self.check(OR, lambda a, b: a or b)
        self.check(NAND, lambda a, b: not (a and b))
        self.check(NOR, lambda a, b: not (a or b))
        self.check(XOR, lambda a, b: a != b)

    def test_not(self):
        self.check(NOT, lambda a: not a)

    def test_three_inputs(self):
        self.check(AND3, lambda a, b, c: a and b and c)


class UnknownInputs(unittest.TestCase):
    def test_output_known_when_unknown_input_does_not_matter(self):
        self.assertIs(AND.evaluate(O, X), O)
        self.assertIs(OR.evaluate(I, Z), I)
        self.assertIs(NAND.evaluate(X, O), I)
        self.assertIs(NOR.evaluate(Z, I), O)
        self.assertIs(AND3.evaluate(X, O, Z), O)

    def test_output_unknown_when_it_depends_on_unknown_input(self):
        self.assertIs(AND.evaluate(I, X), X)
        self.assertIs(OR.evaluate(O, X), X)
        self.assertIs(XOR.evaluate(I, X), X)
        self.assertIs(NOT.evaluate(X), X)
        self.assertIs(NOT.evaluate(Z), X)    # floating input counts as unknown


class Arity(unittest.TestCase):
    def test_wrong_number_of_inputs_raises(self):
        with self.assertRaises(ValueError):
            AND.evaluate(I)
        with self.assertRaises(ValueError):
            NOT.evaluate(I, O)


class Library(unittest.TestCase):
    def test_buf_and_registry(self):
        self.assertIs(BUF.evaluate(I), I)
        self.assertIs(BUF.evaluate(Z), X)
        self.assertEqual(set(GATES), {"AND", "OR", "NAND", "NOR", "XOR", "NOT", "AND3", "BUF"})
        self.assertIs(GATES["NAND"], NAND)

    def test_truth_table(self):
        self.assertEqual(truth_table(AND), [((O, O), O), ((O, I), O), ((I, O), O), ((I, I), I)])
        self.assertEqual(truth_table(NOT), [((O,), I), ((I,), O)])
        self.assertEqual(len(truth_table(AND3)), 8)


class LogicValues(unittest.TestCase):
    def test_of_and_known(self):
        self.assertIs(Logic.of(True), I)
        self.assertIs(Logic.of(False), O)
        self.assertTrue(O.known() and I.known())
        self.assertFalse(X.known() or Z.known())


if __name__ == "__main__":
    unittest.main()
