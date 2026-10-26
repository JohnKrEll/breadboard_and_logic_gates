"""Boolean expressions: tokenizer, parser and expression tree (design.md §6.1–6.4)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .logic import AND, NOT, OR, XOR, Gate, Logic


class ParseError(ValueError):
    def __init__(self, message: str, position: int):
        super().__init__(f"{message} (at position {position + 1})")
        self.message, self.position = message, position


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Const:
    value: Logic


@dataclass(frozen=True)
class Op:
    gate: Gate                      # AND, OR, XOR or NOT from logic.py
    args: tuple


Expr = Var | Const | Op


@dataclass(frozen=True)
class Equation:
    name: str
    expr: Expr
    position: int                   # for error messages


@dataclass(frozen=True)
class Program:
    equations: tuple[Equation, ...]

    @property
    def outputs(self) -> list[str]:
        return [eq.name for eq in self.equations]

    @property
    def inputs(self) -> list[str]:
        """Every name used that no equation defines, in natural order (X2 before X10)."""
        defined = set(self.outputs)
        names = set()
        for eq in self.equations:
            names |= variables(eq.expr)
        return sorted(names - defined, key=natural_key)


def natural_key(name: str):
    m = re.fullmatch(r"(\D*)(\d*)", name)
    return (m.group(1), int(m.group(2)) if m.group(2) else -1)


def variables(expr: Expr) -> set[str]:
    if isinstance(expr, Var):
        return {expr.name}
    if isinstance(expr, Op):
        return set().union(*(variables(a) for a in expr.args))
    return set()


SYMBOLS = {
    "+": "OR", "|": "OR", "∨": "OR",
    "⊕": "XOR", "^": "XOR",
    "·": "AND", "⋅": "AND", "∙": "AND", "*": "AND", "&": "AND", "∧": "AND",
    "¬": "NOT", "!": "NOT", "~": "NOT",
    "'": "PRIME", "’": "PRIME",
    "(": "(", ")": ")", "=": "=", ";": "SEP", "\n": "SEP",
}
NAME = re.compile(r"[A-Z][a-z0-9_]*")


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    position: int


def tokenize(text: str) -> list[Token]:
    tokens, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch in " \t\r":
            i += 1
        elif ch in SYMBOLS:
            tokens.append(Token(SYMBOLS[ch], ch, i))
            i += 1
        elif ch in "01":
            tokens.append(Token("CONST", ch, i))
            i += 1
        elif m := NAME.match(text, i):
            tokens.append(Token("NAME", m.group(), i))
            i = m.end()
        elif ch.isalpha():
            raise ParseError(f"names start with a capital letter, not {ch!r}", i)
        else:
            raise ParseError(f"unexpected {ch!r}", i)
    tokens.append(Token("END", "", len(text)))
    return tokens


ATOM_START = {"NAME", "CONST", "(", "NOT"}


class Parser:
    """Recursive descent: one method per precedence level (design.md §6.2)."""

    def __init__(self, text: str):
        self.tokens = tokenize(text)
        self.i = 0

    def peek(self, ahead: int = 0) -> Token:
        return self.tokens[min(self.i + ahead, len(self.tokens) - 1)]

    def take(self) -> Token:
        token = self.tokens[self.i]
        self.i += 1
        return token

    def expect(self, kind: str, what: str) -> Token:
        if self.peek().kind != kind:
            self.fail(f"expected {what}")
        return self.take()

    def fail(self, message: str):
        token = self.peek()
        found = "end of input" if token.kind == "END" else repr(token.text)
        if token.kind == "SEP" and token.text == "\n":
            found = "end of line"
        raise ParseError(f"{message}, found {found}", token.position)

    def program(self) -> Program:
        equations: list[Equation] = []
        seen: set[str] = set()
        while self.peek().kind != "END":
            if self.peek().kind == "SEP":
                self.take()
                continue
            eq = self.equation()
            if eq.name in seen:
                raise ParseError(f"{eq.name} is defined twice", eq.position)
            seen.add(eq.name)
            equations.append(eq)
            if self.peek().kind not in ("SEP", "END"):
                self.fail("expected an operator or the end of the equation")
        if not equations:
            raise ParseError("type an expression, e.g. F = A + B", 0)
        return Program(tuple(equations))

    def equation(self) -> Equation:
        if self.peek().kind == "NAME" and self.peek(1).kind == "=":
            name = self.take()
            self.take()
            return Equation(name.text, self.or_(), name.position)
        return Equation("F", self.or_(), self.peek().position)

    def or_(self) -> Expr:                          # loosest
        left = self.xor()
        while self.peek().kind == "OR":
            self.take()
            left = Op(OR, (left, self.xor()))
        return left

    def xor(self) -> Expr:
        left = self.and_()
        while self.peek().kind == "XOR":
            self.take()
            left = Op(XOR, (left, self.and_()))
        return left

    def and_(self) -> Expr:                         # "AB" and "A(B+C)" are AND too
        left = self.unary()
        while self.peek().kind == "AND" or self.peek().kind in ATOM_START:
            if self.peek().kind == "AND":
                self.take()
            left = Op(AND, (left, self.unary()))
        return left

    def unary(self) -> Expr:
        if self.peek().kind == "NOT":
            self.take()
            return Op(NOT, (self.unary(),))
        node = self.atom()
        while self.peek().kind == "PRIME":          # A'' is NOT(NOT(A))
            self.take()
            node = Op(NOT, (node,))
        return node

    def atom(self) -> Expr:
        token = self.peek()
        if token.kind == "NAME":
            self.take()
            return Var(token.text)
        if token.kind == "CONST":
            self.take()
            return Const(Logic.ONE if token.text == "1" else Logic.ZERO)
        if token.kind == "(":
            self.take()
            inner = self.or_()
            self.expect(")", "')'")
            return inner
        self.fail("expected a name, 0, 1 or '('")


def parse(text: str) -> Program:
    return Parser(text).program()


SYMBOL_OF = {"AND": "·", "OR": "+", "XOR": "⊕"}


def to_text(expr: Expr) -> str:
    """Fully parenthesised. Parses back to the same tree."""
    if isinstance(expr, Var):
        return expr.name
    if isinstance(expr, Const):
        return expr.value.value
    if expr.gate is NOT:
        return f"{to_text(expr.args[0])}'"
    a, b = expr.args
    return f"({to_text(a)} {SYMBOL_OF[expr.gate.name]} {to_text(b)})"


def evaluate(expr: Expr, env: dict[str, Logic]) -> Logic:
    """Direct evaluation: the reference the circuit simulation is tested against."""
    if isinstance(expr, Var):
        return env[expr.name]
    if isinstance(expr, Const):
        return expr.value
    return expr.gate.evaluate(*(evaluate(a, env) for a in expr.args))
