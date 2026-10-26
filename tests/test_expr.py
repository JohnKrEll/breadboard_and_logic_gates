import random
import unittest

from breadboard.expr import ParseError, evaluate, parse, to_text
from breadboard.logic import Logic

from tests.helpers import random_expr

O, I = Logic.ZERO, Logic.ONE


class Parsing(unittest.TestCase):
    def test_precedence_and_notation(self):
        cases = {
            "A + B": "(A + B)",
            "A+BC": "(A + (B · C))",
            "A + B·C'": "(A + (B · C'))",
            "A'B'": "(A' · B')",
            "(AB)'": "(A · B)'",
            "¬A B": "(A' · B)",
            "!A & ~B | C": "((A' · B') + C)",
            "A ⊕ B + C": "((A ⊕ B) + C)",
            "A + B ⊕ C": "(A + (B ⊕ C))",
            "AB ⊕ C": "((A · B) ⊕ C)",
            "A ^ B * C": "(A ⊕ (B · C))",
            "A(B + C)": "(A · (B + C))",
            "Cin Cout": "(Cin · Cout)",
            "A1B": "(A1 · B)",
            "A''": "A''",
            "A · 1 + 0": "((A · 1) + 0)",
            "A + B + C": "((A + B) + C)",
            "A ⋅ B ∙ C ∧ D": "(((A · B) · C) · D)",
            "A’ ∨ B": "(A' + B)",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                program = parse(text)
                self.assertEqual(program.outputs, ["F"])
                self.assertEqual(to_text(program.equations[0].expr), expected)

    def test_round_trip(self):
        rng = random.Random(1)
        for _ in range(500):
            e = random_expr(rng, 5)
            self.assertEqual(parse(to_text(e)).equations[0].expr, e, to_text(e))

    def test_programs(self):
        p = parse("S = A ⊕ B; C = A·B")
        self.assertEqual((p.inputs, p.outputs), (["A", "B"], ["S", "C"]))
        p = parse("T = A ⊕ B\nS = T ⊕ Cin\n\nCout = AB + T·Cin\n")
        self.assertEqual((p.inputs, p.outputs), (["A", "B", "Cin"], ["T", "S", "Cout"]))
        p = parse("F = X10 + X2 + X1")
        self.assertEqual(p.inputs, ["X1", "X2", "X10"])

    def test_errors(self):
        cases = {
            "A +": ("expected a name, 0, 1 or '(', found end of input", 3),
            "A + * B": ("expected a name, 0, 1 or '(', found '*'", 4),
            "(A + B": ("expected ')', found end of input", 6),
            "A + B)": ("expected an operator or the end of the equation, found ')'", 5),
            "a + b": ("names start with a capital letter, not 'a'", 0),
            "F = A # B": ("unexpected '#'", 6),
            "F = A; F = B": ("F is defined twice", 7),
            "F = ": ("expected a name, 0, 1 or '(', found end of input", 4),
            "": ("type an expression, e.g. F = A + B", 0),
            "A + 2": ("unexpected '2'", 4),
            "F = A +\nG = B": ("expected a name, 0, 1 or '(', found end of line", 7),
        }
        for text, (message, position) in cases.items():
            with self.subTest(text=text):
                with self.assertRaises(ParseError) as caught:
                    parse(text)
                self.assertEqual((caught.exception.message, caught.exception.position), (message, position))

    def test_evaluate(self):
        e = parse("A + B·C'").equations[0].expr
        self.assertIs(evaluate(e, {"A": O, "B": I, "C": O}), I)
        self.assertIs(evaluate(e, {"A": O, "B": I, "C": I}), O)


if __name__ == "__main__":
    unittest.main()
