"""Layer 1: the circuit graph (nets and nodes) and the simulation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter, deque
from typing import Iterable, TypeVar

from .logic import Gate, Logic

N = TypeVar("N", bound="Node")


def combine(values: list[Logic]) -> Logic:
    distinct = set(values)
    return distinct.pop() if len(distinct) == 1 else Logic.X


class Net:
    """A wire: a group of points that are electrically the same."""

    def __init__(self, name: str):
        self.name = name
        self.drivers: list[Node] = []   # nodes whose output is this net
        self.readers: list[Node] = []   # nodes that have this net as an input
        self.value = Logic.Z
        self.strong = False             # driven by a real output (not only via a resistor)
        self.short = False              # strong drivers disagree (0 and 1)

    def resolve(self) -> bool:
        """Recompute the value from the drivers. True if value or strength changed."""
        old = (self.value, self.strong)
        strong = [d.value for d in self.drivers if d.strong and d.value is not Logic.Z]
        weak = [d.value for d in self.drivers if not d.strong and d.value is not Logic.Z]
        self.short = Logic.ONE in strong and Logic.ZERO in strong
        if strong:
            self.value, self.strong = combine(strong), True
        elif weak:
            self.value, self.strong = combine(weak), False
        else:
            self.value, self.strong = Logic.Z, False
        return (self.value, self.strong) != old

    def __repr__(self) -> str:
        return f"<Net {self.name}={self.value.value}>"


class Node(ABC):
    """A component that reads nets and drives at most one net."""

    strong = True   # a "weak" driver loses to a strong one (see ResistorHalf)

    def __init__(self, name: str, inputs: list[Net], output: Net | None):
        self.name = name
        self.inputs = inputs            # ordered: input pin i reads inputs[i]
        self.output = output
        self.value = Logic.X            # last computed output
        for net in inputs:
            net.readers.append(self)    # wiring both directions, once, here
        if output is not None:
            output.drivers.append(self)

    @abstractmethod
    def compute(self) -> Logic: ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}={self.value.value}>"


class GateNode(Node):
    """One gate in the circuit. Outputs Z while its chip is unpowered."""

    def __init__(self, name: str, gate: Gate, inputs: list[Net], output: Net,
                 power: tuple[Net, Net] | None = None):   # None = always powered
        self.gate = gate
        self.data = inputs
        self.power = power
        super().__init__(name, inputs + list(power or ()), output)

    def compute(self) -> Logic:
        if self.power is not None:
            vcc, gnd = self.power
            if vcc.value is not Logic.ONE or gnd.value is not Logic.ZERO:
                return Logic.Z
        return self.gate.evaluate(*(net.value for net in self.data))


class InputNode(Node):
    """A source: a logic switch, or one side of the power supply."""

    def __init__(self, name: str, output: Net, value: Logic = Logic.ZERO):
        super().__init__(name, [], output)
        self.setting = value

    def compute(self) -> Logic:
        return self.setting


class LedNode(Node):
    """Lit (ONE) when the anode is 1 and the cathode is 0."""

    def __init__(self, name: str, anode: Net, cathode: Net):
        super().__init__(name, [anode, cathode], None)

    def compute(self) -> Logic:
        anode, cathode = (net.value for net in self.inputs)
        if anode is Logic.ONE and cathode is Logic.ZERO:
            return Logic.ONE
        if Logic.X in (anode, cathode):
            return Logic.X
        return Logic.ZERO


class ResistorHalf(Node):
    """Passes a strongly driven value from src on to dst, weakly."""

    strong = False

    def __init__(self, name: str, src: Net, dst: Net):
        super().__init__(name, [src], dst)

    def compute(self) -> Logic:
        src = self.inputs[0]
        return src.value if src.strong else Logic.Z


class Circuit:
    def __init__(self):
        self.nets: list[Net] = []
        self.nodes: list[Node] = []
        self.oscillating: set[Node] = set()

    def net(self, name: str) -> Net:
        net = Net(name)
        self.nets.append(net)
        return net

    def add(self, node: N) -> N:
        self.nodes.append(node)
        return node

    def topological_order(self) -> list[Node]:
        """Kahn's algorithm. Nodes that are part of a loop come last."""
        indegree = {node: 0 for node in self.nodes}
        for node in self.nodes:
            if node.output is not None:
                for reader in node.output.readers:
                    indegree[reader] += 1
        queue = deque(node for node in self.nodes if indegree[node] == 0)
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            if node.output is not None:
                for reader in node.output.readers:
                    indegree[reader] -= 1
                    if indegree[reader] == 0:
                        queue.append(reader)
        done = set(order)
        return order + [node for node in self.nodes if node not in done]

    def settle(self, start: Iterable[Node] | None = None, limit: int = 100) -> None:
        """Propagate values until nothing changes. start=None evaluates everything."""
        if start is None:                       # full evaluation after a (re)build
            for net in self.nets:
                net.resolve()
            start = self.topological_order()
        queue = deque(start)
        queued = set(queue)
        evals: Counter[Node] = Counter()
        while queue:
            node = queue.popleft()
            queued.discard(node)
            evals[node] += 1
            new = node.compute()
            if evals[node] > limit:             # still changing: it's oscillating
                new = Logic.X
                self.oscillating.add(node)
            if new is node.value:
                continue
            node.value = new
            if node.output is not None and node.output.resolve():
                for reader in node.output.readers:
                    if reader not in queued:
                        queued.add(reader)
                        queue.append(reader)
        # A node stays reported until something drives it to a known value again,
        # so an unrelated switch flip doesn't hide an oscillation that is still there.
        self.oscillating = {node for node in self.oscillating if node.value is Logic.X}

    def set_input(self, node: InputNode, value: Logic) -> None:
        node.setting = value
        self.settle([node])                     # only what depends on this switch is recomputed
