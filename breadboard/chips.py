"""Layer 2: chip definitions. A chip is data: its gates and which pins they use."""
from __future__ import annotations

from dataclasses import dataclass

from .logic import AND, NAND, NOR, NOT, OR, XOR, Gate


@dataclass(frozen=True)
class ChipSpec:
    name: str
    vcc: int
    gnd: int
    gates: tuple[tuple[Gate, tuple[int, ...], int], ...]   # (gate, input pins, output pin)
    pin_count: int = 14

    def __post_init__(self):
        for gate, inputs, output in self.gates:
            if len(inputs) != gate.arity:
                raise ValueError(f"{self.name}: {gate.name} needs {gate.arity} input pins, "
                                 f"got {len(inputs)}")
            for pin in (*inputs, output, self.vcc, self.gnd):
                if not 1 <= pin <= self.pin_count:
                    raise ValueError(f"{self.name} has no pin {pin}")

    def pin_names(self) -> dict[int, str]:
        """Datasheet names: 1A, 1B, 1Y, …, VCC and GND."""
        names = {self.vcc: "VCC", self.gnd: "GND"}
        for n, (_, inputs, output) in enumerate(self.gates, start=1):
            for letter, pin in zip("ABCD", inputs):
                names[pin] = f"{n}{letter}"
            names[output] = f"{n}Y"
        return names

    def gate_at(self, pin: int) -> int | None:
        """Index of the gate a pin belongs to, or None for power and unused pins."""
        for i, (_, inputs, output) in enumerate(self.gates):
            if pin == output or pin in inputs:
                return i
        return None


def quad_2in(name: str, gate: Gate) -> ChipSpec:   # 7400 / 7408 / 7432 / 7486
    return ChipSpec(name, vcc=14, gnd=7, gates=(
        (gate, (1, 2), 3), (gate, (4, 5), 6), (gate, (9, 10), 8), (gate, (12, 13), 11)))


CHIPS = {
    "7400": quad_2in("74HC00", NAND),
    "7408": quad_2in("74HC08", AND),
    "7432": quad_2in("74HC32", OR),
    "7486": quad_2in("74HC86", XOR),
    "7402": ChipSpec("74HC02", vcc=14, gnd=7, gates=(      # NOR: output pin comes first
        (NOR, (2, 3), 1), (NOR, (5, 6), 4), (NOR, (8, 9), 10), (NOR, (11, 12), 13))),
    "7404": ChipSpec("74HC04", vcc=14, gnd=7, gates=(      # hex inverter
        (NOT, (1,), 2), (NOT, (3,), 4), (NOT, (5,), 6),
        (NOT, (9,), 8), (NOT, (11,), 10), (NOT, (13,), 12))),
}
