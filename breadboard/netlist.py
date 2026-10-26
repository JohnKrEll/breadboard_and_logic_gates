"""The netlist: a circuit as a flat list of gates between named signals (design.md §6.5–6.6)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import product

from .circuit import Circuit, GateNode, InputNode, Net
from .expr import Const, Expr, Program, Var
from .logic import AND, BUF, NAND, NOR, NOT, Gate, Logic

MAX_INPUTS = 8          # 256 truth table rows


@dataclass(frozen=True)
class GateInstance:
    gate: Gate
    inputs: tuple[str, ...]              # signal names
    output: str


@dataclass
class Netlist:
    inputs: list[str]
    outputs: list[str]
    gates: list[GateInstance] = field(default_factory=list)

    @staticmethod
    def from_program(program: Program) -> Netlist:
        netlist = Netlist(program.inputs, program.outputs)
        shared: dict[tuple, str] = {}

        def signal(expr: Expr) -> str:
            if isinstance(expr, Var):
                return expr.name
            if isinstance(expr, Const):
                return expr.value.value                 # "0" or "1"
            key = (expr.gate.name, tuple(signal(a) for a in expr.args))
            if key not in shared:                       # identical subexpressions share a gate
                shared[key] = f"n{len(shared) + 1}"
                netlist.gates.append(GateInstance(expr.gate, key[1], shared[key]))
            return shared[key]

        for eq in program.equations:                    # every equation ends in a BUF
            netlist.gates.append(GateInstance(BUF, (signal(eq.expr),), eq.name))
        return netlist

    def fused(self) -> Netlist:
        """NOT(AND(…)) becomes NAND(…) and NOT(OR(…)) NOR(…), where the inner gate feeds nothing else."""
        users = Counter(s for g in self.gates for s in g.inputs)
        driver = {g.output: g for g in self.gates}
        gates, removed = [], set()
        for g in self.gates:
            inner = driver.get(g.inputs[0]) if g.gate is NOT else None
            if inner is not None and inner.gate.name in ("AND", "OR") and users[inner.output] == 1:
                gates.append(GateInstance(NAND if inner.gate is AND else NOR, inner.inputs, g.output))
                removed.add(inner.output)
            else:
                gates.append(g)
        return Netlist(self.inputs, self.outputs, [g for g in gates if g.output not in removed])

    def to_circuit(self) -> tuple[Circuit, dict[str, InputNode], dict[str, Net]]:
        circuit = Circuit()
        nets: dict[str, Net] = {}

        def net(name: str) -> Net:
            if name not in nets:
                nets[name] = circuit.net(name)
                if name in ("0", "1"):                  # constants are fixed inputs
                    circuit.add(InputNode(name, nets[name], Logic(name)))
            return nets[name]

        inputs = {name: circuit.add(InputNode(name, net(name))) for name in self.inputs}
        for g in self.gates:
            circuit.add(GateNode(g.output, g.gate, [net(s) for s in g.inputs], net(g.output)))
        return circuit, inputs, nets

    def truth_table(self) -> list[tuple[tuple[Logic, ...], tuple[Logic, ...]]]:
        if len(self.inputs) > MAX_INPUTS:
            raise ValueError(f"too many inputs for a truth table ({len(self.inputs)} > {MAX_INPUTS})")
        rows = []
        for values in product((Logic.ZERO, Logic.ONE), repeat=len(self.inputs)):
            circuit, inputs, nets = self.to_circuit()  # fresh each row: power-up state
            for name, value in zip(self.inputs, values):
                inputs[name].setting = value
            circuit.settle()
            rows.append((values, tuple(nets[name].value for name in self.outputs)))
        return rows

    def has_feedback(self) -> bool:
        driver = {g.output: g for g in self.gates}
        state: dict[str, int] = {}                     # 1 = on the current path, 2 = done

        def visit(signal: str) -> bool:
            if signal not in driver or state.get(signal) == 2:
                return False
            if state.get(signal) == 1:
                return True
            state[signal] = 1
            if any(visit(s) for s in driver[signal].inputs):
                return True
            state[signal] = 2
            return False

        return any(visit(g.output) for g in self.gates)

    def gate_counts(self) -> Counter:
        """Gates per type, BUFs not counted (they are only names)."""
        return Counter(g.gate.name for g in self.gates if g.gate is not BUF)
