"""The schematic: a circuit as gate symbols on a grid, with wires between ports (design.md §7.2)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .expr import natural_key
from .logic import BUF, GATES, Gate, Logic
from .netlist import GateInstance, Netlist

NAME = re.compile(r"[A-Z][a-z0-9_]*")
INPUT_NAMES, OUTPUT_NAMES = "ABCDE", "FGHXYZ"


@dataclass(frozen=True)
class Port:
    symbol: str                 # symbol id
    pin: str                    # "out", or "in1", "in2", …

    @property
    def is_output(self) -> bool:
        return self.pin == "out"

    def __str__(self) -> str:
        return f"{self.symbol}.{self.pin}"

    @staticmethod
    def parse(text: str) -> Port:
        symbol, pin = text.split(".")
        return Port(symbol, pin)


@dataclass
class Symbol:
    id: str                     # stable: wires, saved files and positions refer to it
    kind: str                   # "input", "output", "gate" or "const"
    x: int = 0                  # top-left corner, in grid units
    y: int = 0
    name: str = ""              # inputs and outputs: "A", "Cout"; constants: "0" / "1"
    gate: Gate | None = None    # for kind == "gate"
    value: Logic = Logic.ZERO   # an input's switch setting

    @property
    def arity(self) -> int:
        if self.kind == "gate":
            return self.gate.arity
        return 1 if self.kind == "output" else 0

    def input_pins(self) -> list[str]:
        return [f"in{i}" for i in range(1, self.arity + 1)]

    def has_output(self) -> bool:
        return self.kind != "output"

    def size(self) -> tuple[int, int]:
        if self.kind == "gate":
            return 4, 2 * self.arity
        return (2, 2) if self.kind == "const" else (3, 2)

    def pin_offset(self, pin: str) -> tuple[int, int]:
        width, height = self.size()
        if pin == "out":
            return width, height // 2
        return 0, 2 * int(pin[2:]) - 1

    @property
    def label(self) -> str:
        return self.gate.name if self.kind == "gate" else self.name


class Schematic:
    def __init__(self):
        self.symbols: dict[str, Symbol] = {}
        self.sources: dict[Port, Port] = {}     # input port -> the output port that drives it

    # ---------------------------------------------------------------- editing

    def add(self, kind: str, x: int = 0, y: int = 0, name: str = "", gate: Gate | None = None,
            id: str | None = None) -> Symbol:
        if kind not in ("input", "output", "gate", "const"):
            raise ValueError(f"unknown symbol kind {kind!r}")
        if kind == "gate" and gate is None:
            raise ValueError("a gate symbol needs a gate")
        if kind in ("input", "output"):
            name = name or self.free_name(INPUT_NAMES if kind == "input" else OUTPUT_NAMES)
            self._check_name(name)
        if kind == "const" and name not in ("0", "1"):
            raise ValueError("a constant is 0 or 1")
        if id is None:
            prefix = {"input": "in", "output": "out", "gate": "g", "const": "k"}[kind]
            n = 1
            while f"{prefix}{n}" in self.symbols:
                n += 1
            id = f"{prefix}{n}"
        elif id in self.symbols or "." in id:
            raise ValueError(f"bad or duplicate symbol id {id!r}")
        symbol = Symbol(id, kind, x, y, name, gate)
        self.symbols[id] = symbol
        return symbol

    def free_name(self, letters: str, avoid: frozenset[str] = frozenset()) -> str:
        used = {s.name for s in self.symbols.values()} | avoid
        for letter in letters:
            if letter not in used:
                return letter
        n = 1
        while f"{letters[0]}{n}" in used:
            n += 1
        return f"{letters[0]}{n}"

    def _check_name(self, name: str, ignore: str | None = None) -> None:
        if not NAME.fullmatch(name):
            raise ValueError(f"{name!r} is not a valid name (a capital letter, then a-z, 0-9 or _)")
        if any(s.name == name and s.id != ignore for s in self.symbols.values()):
            raise ValueError(f"the name {name} is already used")

    def rename(self, id: str, name: str) -> None:
        if self.symbols[id].kind not in ("input", "output"):
            raise ValueError("only inputs and outputs have names")
        self._check_name(name, ignore=id)
        self.symbols[id].name = name

    def remove(self, id: str) -> None:
        del self.symbols[id]
        self.sources = {i: o for i, o in self.sources.items() if id not in (i.symbol, o.symbol)}

    def connect(self, a: Port, b: Port) -> Port | None:
        """Connect an output port to an input port, in either order. Returns the replaced source."""
        if a.is_output == b.is_output:
            raise ValueError("a wire goes from an output to an input"
                             if a.is_output else "connect an input to an output, not to another input")
        out, inp = (a, b) if a.is_output else (b, a)
        for port in (out, inp):
            symbol = self.symbols.get(port.symbol)
            if symbol is None or not (port.is_output and symbol.has_output()
                                      or port.pin in symbol.input_pins()):
                raise ValueError(f"there is no port {port}")
        old = self.sources.get(inp)
        self.sources[inp] = out
        return old

    def disconnect(self, inp: Port) -> None:
        self.sources.pop(inp, None)

    def fits(self, id: str, x: int, y: int, ignore: frozenset[str] = frozenset()) -> bool:
        """True if the symbol can stand at (x, y): two free columns beside every other symbol
        (so the cells in front of facing ports differ) and one free row above and below."""
        w, h = self.symbols[id].size()
        for other in self.symbols.values():
            if other.id == id or other.id in ignore:
                continue
            ow, oh = other.size()
            if x < other.x + ow + 3 and other.x < x + w + 3 and y < other.y + oh + 2 and other.y < y + h + 2:
                return False
        return True

    def move(self, id: str, x: int, y: int) -> None:
        if not self.fits(id, x, y):
            raise ValueError("too close to another symbol")
        self.symbols[id].x, self.symbols[id].y = x, y

    # ---------------------------------------------------------------- queries

    def port_xy(self, port: Port) -> tuple[int, int]:
        symbol = self.symbols[port.symbol]
        dx, dy = symbol.pin_offset(port.pin)
        return symbol.x + dx, symbol.y + dy

    def ports(self, symbol: Symbol) -> list[Port]:
        pins = symbol.input_pins() + (["out"] if symbol.has_output() else [])
        return [Port(symbol.id, pin) for pin in pins]

    def nets(self) -> dict[Port, list[Port]]:
        """Output port -> the input ports it drives."""
        nets: dict[Port, list[Port]] = {}
        for inp, out in self.sources.items():
            nets.setdefault(out, []).append(inp)
        return nets

    def bounds(self) -> tuple[int, int, int, int]:
        if not self.symbols:
            return 0, 0, 0, 0
        return (min(s.x for s in self.symbols.values()), min(s.y for s in self.symbols.values()),
                max(s.x + s.size()[0] for s in self.symbols.values()),
                max(s.y + s.size()[1] for s in self.symbols.values()))

    def by_name(self, name: str) -> Symbol | None:
        return next((s for s in self.symbols.values() if s.kind in ("input", "output") and s.name == name), None)

    def problems(self) -> list[str]:
        problems = []
        driven = {out.symbol for out in self.sources.values()}
        for s in sorted(self.symbols.values(), key=lambda s: (s.x, s.y)):
            if s.kind == "gate":
                for pin in s.input_pins():
                    if Port(s.id, pin) not in self.sources:
                        problems.append(f"{s.gate.name} gate {s.id}: input {pin[2:]} is not connected")
            elif s.kind == "output" and Port(s.id, "in1") not in self.sources:
                problems.append(f"output {s.name} is not connected")
            elif s.kind == "input" and s.id not in driven:
                problems.append(f"input {s.name} isn't connected to anything")
        return problems

    # ---------------------------------------------------------------- conversions

    def signal(self, port: Port | None, consumer: Port) -> str:
        if port is None:
            return f"open:{consumer}"             # nothing drives it: a floating net
        symbol = self.symbols[port.symbol]
        return symbol.name if symbol.kind in ("input", "const") else symbol.id

    def to_netlist(self) -> Netlist:
        inputs = sorted((s for s in self.symbols.values() if s.kind == "input"), key=lambda s: natural_key(s.name))
        outputs = sorted((s for s in self.symbols.values() if s.kind == "output"), key=lambda s: (s.y, s.x))
        netlist = Netlist([s.name for s in inputs], [s.name for s in outputs])
        for s in self.symbols.values():
            if s.kind == "gate":
                ins = tuple(self.signal(self.sources.get(Port(s.id, p)), Port(s.id, p)) for p in s.input_pins())
                netlist.gates.append(GateInstance(s.gate, ins, s.id))
        for s in outputs:
            port = Port(s.id, "in1")
            netlist.gates.append(GateInstance(BUF, (self.signal(self.sources.get(port), port),), s.name))
        return netlist

    @staticmethod
    def from_netlist(netlist: Netlist) -> Schematic:
        """Symbols and wires for a netlist, arranged by auto_place (§7.4)."""
        from .placement import auto_place

        alias = {g.output: g.inputs[0] for g in netlist.gates if g.gate is BUF}
        real = [g for g in netlist.gates if g.gate is not BUF]

        def source(signal: str) -> str:
            seen = set()
            while signal in alias:
                if signal in seen:
                    raise ValueError(f"{signal} is only defined in terms of itself")
                seen.add(signal)
                signal = alias[signal]
            return signal

        sch = Schematic()
        port_of: dict[str, Port] = {}
        for name in netlist.inputs:
            port_of[name] = Port(sch.add("input", name=name).id, "out")
        for g in real:
            port_of[g.output] = Port(sch.add("gate", gate=g.gate).id, "out")

        def driver(signal: str) -> Port | None:
            signal = source(signal)
            if signal in ("0", "1") and signal not in port_of:
                port_of[signal] = Port(sch.add("const", name=signal).id, "out")
            return port_of.get(signal)

        for g in real:
            for i, signal in enumerate(g.inputs, start=1):
                if (src := driver(signal)) is not None:
                    sch.connect(src, Port(port_of[g.output].symbol, f"in{i}"))
        for name in netlist.outputs:
            out = sch.add("output", name=name)
            if (src := driver(name)) is not None:
                sch.connect(src, Port(out.id, "in1"))
        auto_place(sch)
        return sch

    def to_dict(self) -> dict:
        symbols = []
        for s in self.symbols.values():
            d = {"id": s.id, "kind": s.kind, "x": s.x, "y": s.y}
            if s.kind == "gate":
                d["gate"] = s.gate.name
            else:
                d["name"] = s.name
            if s.kind == "input":
                d["value"] = s.value.value
            symbols.append(d)
        wires = [{"from": str(o), "to": str(i)} for i, o in self.sources.items()]
        return {"symbols": symbols, "wires": wires}

    @staticmethod
    def from_dict(data: dict) -> Schematic:
        sch = Schematic()
        for d in data["symbols"]:
            gate = None
            if d["kind"] == "gate":
                if d.get("gate") not in GATES:
                    raise ValueError(f"unknown gate {d.get('gate')!r}")
                gate = GATES[d["gate"]]
            s = sch.add(d["kind"], d["x"], d["y"], d.get("name", ""), gate, d["id"])
            if "value" in d:
                s.value = Logic(d["value"])
        for w in data["wires"]:
            sch.connect(Port.parse(w["from"]), Port.parse(w["to"]))
        return sch

    def copy(self) -> Schematic:
        return Schematic.from_dict(self.to_dict())

    def renamed(self, ids: dict[str, str]) -> Schematic:
        """A copy (without wires) whose symbol ids are replaced by ids[old]; symbols not in
        `ids` are left out. Used to carry positions over to another schematic of the circuit."""
        sch = Schematic()
        for s in self.symbols.values():
            new = ids.get(s.id)
            if new is not None and new not in sch.symbols:          # constants may merge
                copy = sch.add(s.kind, s.x, s.y, s.name, s.gate, new)
                copy.value = s.value
        return sch
