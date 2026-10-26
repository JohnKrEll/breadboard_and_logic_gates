"""Layer 2: the physical breadboard, and building a Circuit from it."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, TypeVar

from .chips import ChipSpec
from .circuit import Circuit, GateNode, InputNode, LedNode, Net, Node, ResistorHalf
from .logic import Logic

ROWS = tuple("abcdefghij")
TOP_ROWS = tuple("abcde")
RAILS = ("T+", "T-", "B+", "B-")

P = TypeVar("P", bound="Part")


def parse_hole(hole: str) -> tuple[str, int]:
    """Split a hole name into row and column: "c5" -> ("c", 5), "T+3" -> ("T+", 3)."""
    row = hole[:2] if hole[:2] in RAILS else hole[:1]
    column = hole[len(row):]
    if (row not in RAILS and row not in ROWS) or not (column.isascii() and column.isdigit()):
        raise ValueError(f"no such hole: {hole!r}")
    return row, int(column)


def strip_of(hole: str) -> str:
    """The strip a hole belongs to. Holes in the same strip are always connected."""
    row, column = parse_hole(hole)
    if row in RAILS:
        return row                                              # "T+3" -> "T+"
    return f"{'top' if row in TOP_ROWS else 'bot'}{column}"     # "c5"  -> "top5"


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]        # path halving
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


class Part(ABC):
    """Something physical placed on the board."""

    uid: int | None = None          # given by Breadboard.place(); schematic ids are made from it

    @abstractmethod
    def pins(self) -> dict[str, str]: ...                       # pin name -> hole

    def instantiate(self, circuit: Circuit, net_of: Callable[[str], Net]) -> list[Node]:
        return []                                               # wires create no nodes


class Wire(Part):
    def __init__(self, a: str, b: str):
        self.a, self.b = a, b

    def pins(self) -> dict[str, str]:
        return {"a": self.a, "b": self.b}

    def __repr__(self) -> str:
        return f"Wire({self.a!r}, {self.b!r})"


class PowerSupply(Part):
    def __init__(self, plus: str = "T+1", minus: str = "T-1"):
        self.plus, self.minus = plus, minus

    def pins(self) -> dict[str, str]:
        return {"+": self.plus, "-": self.minus}

    def instantiate(self, circuit, net_of):
        return [circuit.add(InputNode("power +", net_of(self.plus), Logic.ONE)),
                circuit.add(InputNode("power -", net_of(self.minus), Logic.ZERO))]

    def __repr__(self) -> str:
        return f"PowerSupply({self.plus!r}, {self.minus!r})"


class LogicInput(Part):
    """A switch the user flips between 0 and 1."""

    def __init__(self, hole: str, value: Logic = Logic.ZERO, label: str = ""):
        self.hole, self.value, self.label = hole, value, label

    def pins(self) -> dict[str, str]:
        return {"out": self.hole}

    def instantiate(self, circuit, net_of):
        return [circuit.add(InputNode(f"input at {self.hole}", net_of(self.hole), self.value))]

    def __repr__(self) -> str:
        return f"LogicInput({self.hole!r}, {self.value})"


class Led(Part):
    def __init__(self, anode: str, cathode: str, label: str = ""):
        self.anode, self.cathode, self.label = anode, cathode, label

    def pins(self) -> dict[str, str]:
        return {"anode": self.anode, "cathode": self.cathode}

    def instantiate(self, circuit, net_of):
        return [circuit.add(LedNode(f"LED at {self.anode}",
                                    net_of(self.anode), net_of(self.cathode)))]

    def __repr__(self) -> str:
        return f"Led({self.anode!r}, {self.cathode!r})"


class Resistor(Part):
    """A weak connection: enough for pull-ups, pull-downs and LED resistors."""

    def __init__(self, a: str, b: str):
        self.a, self.b = a, b

    def pins(self) -> dict[str, str]:
        return {"a": self.a, "b": self.b}

    def instantiate(self, circuit, net_of):
        a, b = net_of(self.a), net_of(self.b)
        return [circuit.add(ResistorHalf(f"resistor {self.a}->{self.b}", a, b)),
                circuit.add(ResistorHalf(f"resistor {self.b}->{self.a}", b, a))]

    def __repr__(self) -> str:
        return f"Resistor({self.a!r}, {self.b!r})"


class Chip(Part):
    """A DIP chip straddling the channel, notch to the left, pin 1 at f{column}."""

    def __init__(self, spec: ChipSpec, column: int):
        self.spec, self.column = spec, column

    def pin_hole(self, pin: int) -> str:
        half = self.spec.pin_count // 2
        if pin <= half:
            return f"f{self.column + pin - 1}"
        return f"e{self.column + self.spec.pin_count - pin}"

    def pins(self) -> dict[str, str]:
        return {str(pin): self.pin_hole(pin) for pin in range(1, self.spec.pin_count + 1)}

    def instantiate(self, circuit, net_of):
        net = lambda pin: net_of(self.pin_hole(pin))
        power = (net(self.spec.vcc), net(self.spec.gnd))
        return [circuit.add(GateNode(f"{self.spec.name}@{self.column} pin {out}", gate,
                                     [net(p) for p in ins], net(out), power))
                for gate, ins, out in self.spec.gates]

    def __repr__(self) -> str:
        return f"Chip({self.spec.name!r}, {self.column})"


class Breadboard:
    def __init__(self, columns: int = 30):
        self.columns = columns
        self.parts: list[Part] = []
        self.nodes: dict[Part, list[Node]] = {}
        self.circuit = Circuit()
        self._uf = UnionFind()
        self._nets: dict[str, Net] = {}
        self._next_uid = 1

    def place(self, part: P) -> P:
        holes = list(part.pins().values())
        for hole in holes:
            self._check_hole(hole)
            if self.part_at(hole) is not None:
                raise ValueError(f"hole {hole} is already in use")
        if len(set(holes)) != len(holes):
            raise ValueError("a part can't use the same hole twice")
        if part.uid is None:
            part.uid = self._next_uid
            self._next_uid += 1
        self.parts.append(part)
        self.build()
        return part

    def remove(self, part: Part) -> None:
        self.parts.remove(part)
        self.build()

    def resize(self, columns: int) -> None:
        """Change the number of columns, e.g. 30 (half size) or 63 (full size)."""
        for part in self.parts:
            for hole in part.pins().values():
                if not 1 <= parse_hole(hole)[1] <= columns:
                    raise ValueError(f"{part} would be off a {columns}-column board")
        self.columns = columns
        self.build()

    def part_at(self, hole: str) -> Part | None:
        for part in self.parts:
            if hole in part.pins().values():
                return part
        return None

    def _check_hole(self, hole: str) -> None:
        _, column = parse_hole(hole)
        if not 1 <= column <= self.columns:
            raise ValueError(f"hole {hole} is off the board")

    def build(self) -> None:
        """Rebuild the circuit from the parts on the board."""
        uf = UnionFind()
        for part in self.parts:
            if isinstance(part, Wire):
                uf.union(strip_of(part.a), strip_of(part.b))
        circuit = Circuit()
        nets: dict[str, Net] = {}

        def net_of(hole: str) -> Net:               # one Net object per union-find root
            root = uf.find(strip_of(hole))
            if root not in nets:
                nets[root] = circuit.net(root)
            return nets[root]

        old, old_oscillating = self.nodes, self.circuit.oscillating
        self.nodes = {}
        for part in self.parts:
            new = part.instantiate(circuit, net_of)
            for prev, node in zip(old.get(part, []), new):
                node.value = prev.value             # keep latch state across rewiring
                if prev in old_oscillating:
                    circuit.oscillating.add(node)
            self.nodes[part] = new
        circuit.settle()
        self.circuit, self._uf, self._nets = circuit, uf, nets

    def toggle(self, inp: LogicInput) -> None:
        self.set(inp, Logic.ZERO if inp.value is Logic.ONE else Logic.ONE)

    def set(self, inp: LogicInput, value: Logic) -> None:
        if not value.known():
            raise ValueError("a logic input is either 0 or 1")
        inp.value = value
        self.circuit.set_input(self.nodes[inp][0], value)

    def led(self, led: Led) -> Logic:
        return self.nodes[led][0].value

    def net_at(self, hole: str) -> Net | None:
        """The net a hole belongs to, or None if no part is connected to it."""
        return self._nets.get(self._uf.find(strip_of(hole)))

    def diagnose(self) -> list[str]:
        """Explain what is wrong with the circuit, in plain words."""
        problems = []
        for net in self.circuit.nets:
            if net.short:
                problems.append(f"short circuit on net {net.name}")
        for part, nodes in self.nodes.items():
            if not isinstance(part, Chip):
                continue
            spec = part.spec
            vcc = self.net_at(part.pin_hole(spec.vcc))
            gnd = self.net_at(part.pin_hole(spec.gnd))
            if vcc.value is not Logic.ONE or gnd.value is not Logic.ZERO:
                problems.append(f"{spec.name} at column {part.column} is not powered")
                continue
            for (_, ins, _), node in zip(spec.gates, nodes):
                if not node.output.readers:
                    continue                        # unused gate on the chip
                for pin, net in zip(ins, node.data):
                    if net.value is Logic.Z:
                        problems.append(f"{spec.name} at column {part.column}: "
                                        f"input pin {pin} is floating")
        for node in sorted(self.circuit.oscillating, key=lambda n: n.name):
            problems.append(f"oscillation at {node.name}")
        return problems
