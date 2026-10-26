"""Layer 1: logic values and gates."""
from __future__ import annotations

from enum import Enum
from itertools import product
from typing import Callable


class Logic(Enum):
    ZERO = "0"
    ONE = "1"
    Z = "Z"  # floating: nothing drives this net
    X = "X"  # unknown: conflicting drivers, undefined input, oscillation, power-up state

    @staticmethod
    def of(value: bool) -> Logic:
        return Logic.ONE if value else Logic.ZERO

    def known(self) -> bool:
        return self is Logic.ZERO or self is Logic.ONE


class Gate:
    """A gate type such as AND. The behaviour is a plain bool function."""

    def __init__(self, name: str, arity: int, expression: Callable[..., bool]):
        self.name = name
        self.arity = arity
        self._expression = expression

    def evaluate(self, *inputs: Logic) -> Logic:
        if len(inputs) != self.arity:
            raise ValueError(f"{self.name} takes {self.arity} inputs, got {len(inputs)}")
        unknown = [i for i, v in enumerate(inputs) if not v.known()]
        bits = [v is Logic.ONE for v in inputs]
        results = set()
        for guess in product((False, True), repeat=len(unknown)):
            for i, b in zip(unknown, guess):
                bits[i] = b
            results.add(bool(self._expression(*bits)))
            if len(results) > 1:
                return Logic.X          # output depends on the unknown input
        return Logic.of(results.pop())  # same answer whatever the unknowns are

    def __repr__(self) -> str:
        return f"Gate({self.name!r}, {self.arity})"


AND = Gate("AND", 2, lambda a, b: a and b)
OR = Gate("OR", 2, lambda a, b: a or b)
NAND = Gate("NAND", 2, lambda a, b: not (a and b))
NOR = Gate("NOR", 2, lambda a, b: not (a or b))
XOR = Gate("XOR", 2, lambda a, b: a != b)
NOT = Gate("NOT", 1, lambda a: not a)
AND3 = Gate("AND3", 3, lambda a, b, c: a and b and c)
BUF = Gate("BUF", 1, lambda a: a)       # "this output is that signal" (netlists, §6.5)

GATES = {g.name: g for g in (AND, OR, NAND, NOR, XOR, NOT, AND3, BUF)}


def truth_table(gate: Gate) -> list[tuple[tuple[Logic, ...], Logic]]:
    return [(values, gate.evaluate(*values))
            for values in product((Logic.ZERO, Logic.ONE), repeat=gate.arity)]
