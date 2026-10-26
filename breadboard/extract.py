"""Breadboard -> schematic, with stable symbol ids and live values (design.md §7.6)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .board import Breadboard, Chip, Led, LogicInput, Part, PowerSupply, parse_hole
from .circuit import Net, ResistorHalf
from .placement import auto_place
from .schematic import INPUT_NAMES, OUTPUT_NAMES, Port, Schematic


@dataclass
class Extraction:
    schematic: Schematic
    live: dict[Port, Net] = field(default_factory=dict)           # source port -> the board net
    problems: list[str] = field(default_factory=list)
    parts: dict[str, Part] = field(default_factory=dict)          # symbol id -> switch / LED / chip
    gates: dict[str, tuple[Chip, int]] = field(default_factory=dict)   # symbol id -> (chip, index)


def switch_id(part: LogicInput) -> str:
    return f"s{part.uid}"


def led_id(part: Led) -> str:
    return f"l{part.uid}"


def gate_id(chip: Chip, index: int) -> str:
    return f"c{chip.uid}g{index + 1}"


def _position(hole: str) -> tuple[int, str]:
    row, column = parse_hole(hole)
    return column, row


def extract(board: Breadboard, previous: Schematic | None = None) -> Extraction:
    """The board's circuit as a schematic. Symbols that exist in `previous` keep their
    positions and names; new ones are placed automatically."""
    sch = Schematic()
    result = Extraction(sch)
    old = previous.symbols if previous else {}
    ids = {switch_id(p) for p in board.parts if isinstance(p, LogicInput)}
    ids |= {led_id(p) for p in board.parts if isinstance(p, Led)}
    reserved = frozenset(s.name for id, s in old.items() if id in ids)

    rails: dict[Net, str] = {}
    for part, nodes in board.nodes.items():
        if isinstance(part, PowerSupply):
            rails[nodes[0].output], rails[nodes[1].output] = "1", "0"

    strong: dict[Net, Port] = {}

    def claim(net: Net, port: Port) -> None:
        if net in strong or net in rails:
            result.problems.append(f"net {net.name} has more than one driver; the schematic shows the first")
        else:
            strong[net] = port
            result.live[port] = net

    def add_named(kind: str, part: Part, id: str, letters: str):
        names = [getattr(part, "label", ""), old[id].name if id in old else ""]
        for name in names:
            if name:
                try:
                    return sch.add(kind, name=name, id=id)
                except ValueError:
                    result.problems.append(f"the name {name} is used twice")
        return sch.add(kind, name=sch.free_name(letters, reserved), id=id)

    for part in sorted((p for p in board.parts if isinstance(p, LogicInput)), key=lambda p: _position(p.hole)):
        s = add_named("input", part, switch_id(part), INPUT_NAMES)
        s.value = part.value
        result.parts[s.id] = part
        claim(board.nodes[part][0].output, Port(s.id, "out"))

    gates = []
    for part in board.parts:
        if isinstance(part, Chip):
            for i, node in enumerate(board.nodes[part]):
                if node.output.readers or any(net.drivers for net in node.data):   # skip unused gates
                    s = sch.add("gate", gate=node.gate, id=gate_id(part, i))
                    result.parts[s.id] = part
                    result.gates[s.id] = (part, i)
                    claim(node.output, Port(s.id, "out"))
                    gates.append((s, node))

    def const(value: str, net: Net) -> Port:
        id = f"k{value}"
        if id not in sch.symbols:
            sch.add("const", name=value, id=id)
            result.live[Port(id, "out")] = net
        return Port(id, "out")

    def driver_of(net: Net) -> Port | None:
        if net in strong:
            return strong[net]
        if net in rails:
            return const(rails[net], net)
        for d in net.drivers:                      # through a resistor: pull-up, pull-down, series
            if isinstance(d, ResistorHalf):
                other = d.inputs[0]
                if other in strong:
                    return strong[other]
                if other in rails:
                    return const(rails[other], other)
        return None

    for s, node in gates:
        for k, net in enumerate(node.data, start=1):
            if (src := driver_of(net)) is not None:
                sch.connect(src, Port(s.id, f"in{k}"))
    for part in sorted((p for p in board.parts if isinstance(p, Led)), key=lambda p: _position(p.anode)):
        out = add_named("output", part, led_id(part), OUTPUT_NAMES)
        result.parts[out.id] = part
        if (src := driver_of(board.nodes[part][0].inputs[0])) is not None:
            sch.connect(src, Port(out.id, "in1"))

    fixed = frozenset(id for id in sch.symbols if id in old)
    for id in fixed:
        sch.symbols[id].x, sch.symbols[id].y = old[id].x, old[id].y
    auto_place(sch, fixed)
    return result
