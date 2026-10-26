"""Netlist -> parts on a breadboard: chips, power, wires, switches and LEDs (design.md §6.7)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterator

from .board import Breadboard, Chip, Led, LogicInput, Part, PowerSupply, Wire, parse_hole, strip_of
from .chips import CHIPS
from .logic import BUF
from .netlist import GateInstance, Netlist

GATE_CHIPS = {"AND": "7408", "OR": "7432", "XOR": "7486", "NOT": "7404", "NAND": "7400", "NOR": "7402"}
FIRST_CHIP = 2       # column of the first chip's pin 1
CHIP_PITCH = 8       # 7 columns per chip + 1 free column between chips
MIN_COLUMNS = 30


class LayoutError(ValueError):
    pass


@dataclass
class Layout:
    board: Breadboard
    inputs: dict[str, LogicInput]               # input name -> its switch
    leds: dict[str, Led]                        # output name -> its LED
    gates: dict[str, tuple[Chip, int]]          # gate output signal -> (chip, gate index)


def holes_of(strip: str) -> list[str]:
    side, column = strip[:3], strip[3:]
    rows = "abcde" if side == "top" else "jihgf"       # far end first, away from the chip
    return [f"{row}{column}" for row in rows]


def column_of(hole: str) -> int:
    return parse_hole(hole)[1]


def free_strips(chip_count: int) -> Iterator[str]:
    """Strips in columns no chip uses: the gaps between chips, then past the last chip."""
    taken = {FIRST_CHIP + CHIP_PITCH * k + i for k in range(chip_count) for i in range(7)}
    column = 1
    while True:
        if column not in taken:
            yield f"top{column}"
            yield f"bot{column}"
        column += 1


def chips_needed(netlist: Netlist) -> Counter:
    """Chip name -> how many, for the Expression tab's summary. Gates with no chip are left out."""
    count = Counter()
    for name, n in netlist.gate_counts().items():
        if name in GATE_CHIPS:
            spec = CHIPS[GATE_CHIPS[name]]
            count[spec.name] = -(-n // len(spec.gates))      # rounded up
    return count


def layout(netlist: Netlist) -> Layout:
    alias = {g.output: g.inputs[0] for g in netlist.gates if g.gate is BUF}
    real = [g for g in netlist.gates if g.gate is not BUF]

    def source(signal: str) -> str:                    # follow F = G = … down to a real signal
        seen = set()
        while signal in alias:
            if signal in seen:
                raise LayoutError(f"{signal} is only defined in terms of itself")
            seen.add(signal)
            signal = alias[signal]
        return signal

    # 1. chips: fill each chip type's gates before starting a new chip of that type
    chips: list[Chip] = []
    free_slots: dict[str, list[tuple[Chip, int]]] = {}
    placed: dict[GateInstance, tuple[Chip, int]] = {}
    for g in real:
        if g.gate.name not in GATE_CHIPS:
            raise LayoutError(f"there is no chip for {g.gate.name} gates")
        key = GATE_CHIPS[g.gate.name]
        slots = free_slots.setdefault(key, [])
        if not slots:
            chip = Chip(CHIPS[key], FIRST_CHIP + CHIP_PITCH * len(chips))
            chips.append(chip)
            slots.extend((chip, i) for i in range(len(chip.spec.gates)))
        placed[g] = slots.pop(0)

    used: set[str] = set()
    parts: list[Part] = []
    strips = free_strips(len(chips))

    def take(strip: str) -> str:
        for hole in holes_of(strip):
            if hole not in used:
                used.add(hole)
                return hole
        raise LayoutError(f"strip {strip} is full")

    def take_rail(rail: str, near: int) -> str:
        for distance in range(1000):
            for column in (near + distance, near - distance):
                hole = f"{rail}{column}"
                if column >= 1 and hole not in used:
                    used.add(hole)
                    return hole
        raise LayoutError(f"rail {rail} is full")

    def add(part: Part) -> Part:
        parts.append(part)
        used.update(part.pins().values())
        return part

    # 2. power: supply on the top rails, GND bridged to the bottom rail, each chip wired up
    add(PowerSupply("T+1", "T-1"))
    add(Wire("T-2", "B-2"))
    for chip in chips:
        add(chip)
    for chip in chips:
        vcc, gnd = chip.pin_hole(chip.spec.vcc), chip.pin_hole(chip.spec.gnd)
        add(Wire(take(strip_of(vcc)), take_rail("T+", column_of(vcc))))
        add(Wire(take(strip_of(gnd)), take_rail("B-", column_of(gnd))))

    # 3. where each signal is available, and how many connections it still has to feed
    demand = Counter(source(s) for g in real for s in g.inputs)
    demand.update(source(o) for o in netlist.outputs)
    home: dict[str, list[str]] = {}
    inputs: dict[str, LogicInput] = {}
    for name in netlist.inputs:
        strip = next(strips)
        inputs[name] = add(LogicInput(holes_of(strip)[0], label=name))
        home[name] = [strip]
    for g in real:
        chip, i = placed[g]
        home[g.output] = [strip_of(chip.pin_hole(chip.spec.gates[i][2]))]

    def tap(signal: str, near: int) -> str:
        """A free hole on the signal's net, extending it onto a new strip when one fills up."""
        if signal in ("0", "1"):
            return take_rail("T+" if signal == "1" else "T-", near)
        if signal not in home:
            raise LayoutError(f"{signal} is not connected")
        strip = home[signal][-1]
        if sum(h not in used for h in holes_of(strip)) == 1 and demand[signal] > 1:
            extra = next(strips)
            add(Wire(take(strip), take(extra)))
            home[signal].append(extra)
            strip = extra
        demand[signal] -= 1
        return take(strip)

    # 4. wire every gate input to its signal
    for g in real:
        chip, i = placed[g]
        for signal, pin in zip(g.inputs, chip.spec.gates[i][1]):
            if source(signal).startswith("open:"):
                continue                                # unconnected in the schematic: left floating
            hole = chip.pin_hole(pin)
            add(Wire(tap(source(signal), column_of(hole)), take(strip_of(hole))))

    # 5. one LED per output, cathode into the nearest GND rail
    leds: dict[str, Led] = {}
    for name in netlist.outputs:
        signal = source(name)
        anode = take(next(strips)) if signal.startswith("open:") else tap(signal, FIRST_CHIP)
        rail = "T-" if anode[0] in "abcdeT" else "B-"
        leds[name] = add(Led(anode, take_rail(rail, column_of(anode)), label=name))

    # 6. the board grows to fit
    board = Breadboard(max([MIN_COLUMNS] + [column_of(h) for h in used]))
    for part in parts:
        board.place(part)
    return Layout(board, inputs, leds, {g.output: placed[g] for g in real})
