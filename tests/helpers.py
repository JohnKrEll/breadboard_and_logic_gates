"""Shared test helpers."""
import random

from breadboard.expr import Const, Op, Var
from breadboard.logic import AND, NOT, OR, XOR, Logic

EXAMPLES = [
    "F = A + B",
    "S = A ⊕ B; C = AB",
    "S = A ⊕ B ⊕ Cin; Cout = AB + Cin(A ⊕ B)",
    "F = A·S' + B·S",
    "F = (A⊕B)(C⊕D)(A⊕C)(B⊕D)(A⊕D) + (AB)'(CD)' + A'B'C'D'",
    "F = 1; G = A; H = G'",
    "F = (AB)' + (A + B)'",
    "F = A·A·A·A·A·A + A'",
]
LATCH = "Q = (R + Qn)'; Qn = (S + Q)'"


def random_expr(rng: random.Random, depth: int, names: str = "ABCD"):
    if depth == 0 or rng.random() < 0.25:
        if rng.random() < 0.08:
            return Const(rng.choice((Logic.ZERO, Logic.ONE)))
        return Var(rng.choice(names))
    kind = rng.choice((AND, OR, XOR, NOT, NOT))
    if kind is NOT:
        return Op(NOT, (random_expr(rng, depth - 1, names),))
    return Op(kind, (random_expr(rng, depth - 1, names), random_expr(rng, depth - 1, names)))


def named_table(netlist):
    """A truth table keyed by names, so column order doesn't matter."""
    return {frozenset(zip(netlist.inputs, ins)): frozenset(zip(netlist.outputs, outs))
            for ins, outs in netlist.truth_table()}
