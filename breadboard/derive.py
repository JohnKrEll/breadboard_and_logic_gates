"""Netlist -> Boolean expressions, the reverse of parsing (design.md §7.7)."""
from __future__ import annotations

from .expr import Const, Expr, Op, Var
from .logic import AND, BUF, NOT, OR, XOR, Logic
from .netlist import Netlist

PRECEDENCE = {"OR": 1, "XOR": 2, "AND": 3}
SYMBOL = {"AND": "·", "OR": " + ", "XOR": " ⊕ "}


def pretty(expr: Expr) -> str:
    """As few parentheses as the precedence rules allow; parses back to the same tree."""
    if isinstance(expr, Var):
        return expr.name
    if isinstance(expr, Const):
        return expr.value.value
    if expr.gate is NOT:
        inner = expr.args[0]
        text = pretty(inner)
        return f"{text}'" if not isinstance(inner, Op) or inner.gate is NOT else f"({text})'"
    level = PRECEDENCE[expr.gate.name]
    a, b = expr.args

    def side(e: Expr, right: bool) -> str:
        text = pretty(e)
        if isinstance(e, Op) and e.gate is not NOT:
            inner = PRECEDENCE[e.gate.name]
            if inner < level or (right and inner == level):    # the parser groups from the left
                return f"({text})"
        return text

    return side(a, False) + SYMBOL[expr.gate.name] + side(b, True)


def as_expr(gate_name: str, args: list[Expr]) -> Expr:
    """A gate written with the operators the parser knows."""
    if gate_name == "NOT":
        return Op(NOT, (args[0],))
    base = {"AND": AND, "NAND": AND, "AND3": AND, "OR": OR, "NOR": OR, "XOR": XOR}[gate_name]
    expr = args[0]
    for arg in args[1:]:
        expr = Op(base, (expr, arg))
    return Op(NOT, (expr,)) if gate_name in ("NAND", "NOR") else expr


def derive(netlist: Netlist) -> str:
    """One equation per output. Loops without a name on them get one (T1, T2, …)."""
    driver = {g.output: g for g in netlist.gates}

    def through(signal: str) -> str:               # look through BUFs (F = G, outputs)
        seen = set()
        while signal in driver and driver[signal].gate is BUF and signal not in seen:
            seen.add(signal)
            signal = driver[signal].inputs[0]
        return signal

    named: dict[str, str] = {}                     # gate signal -> the name it is written as
    for name in netlist.outputs:
        if through(name) in driver:
            named.setdefault(through(name), name)
    taken = set(netlist.inputs) | set(netlist.outputs)
    extra: list[str] = []
    state: dict[str, int] = {}                     # 1 = on the current path, 2 = done

    def cut_loops(signal: str, root: str) -> None:
        signal = through(signal)
        if signal not in driver or state.get(signal) == 2:
            return
        if signal in named and (signal != root or state.get(signal) == 1):
            return                                 # written as a name: the loop is cut here
        if state.get(signal) == 1:                 # back on the current path: name it
            n = 1
            while f"T{n}" in taken:
                n += 1
            named[signal] = f"T{n}"
            taken.add(f"T{n}")
            extra.append(signal)
            return
        state[signal] = 1
        for s in driver[signal].inputs:
            cut_loops(s, root)
        state[signal] = 2

    roots = [through(name) for name in netlist.outputs]
    for root in roots:
        cut_loops(root, root)

    def build(signal: str, top: bool = False) -> Expr:
        signal = through(signal)
        if not top and signal in named:
            return Var(named[signal])
        if signal in ("0", "1"):
            return Const(Logic(signal))
        if signal.startswith("open:"):
            raise ValueError(f"{signal[5:]} is not connected")
        if signal not in driver:
            return Var(signal)
        g = driver[signal]
        return as_expr(g.gate.name, [build(s) for s in g.inputs])

    equations = [f"{name} = {pretty(build(root, top=True))}" for name, root in zip(netlist.outputs, roots)]
    equations += [f"{named[signal]} = {pretty(build(signal, top=True))}" for signal in extra]
    return "\n".join(equations)
