"""Breadboard and logic gate simulator. See design.md."""
from .board import (Breadboard, Chip, Led, LogicInput, Part, PowerSupply, Resistor, Wire,
                    parse_hole, strip_of)
from .chips import CHIPS, ChipSpec
from .circuit import Circuit, GateNode, InputNode, LedNode, Net, Node, ResistorHalf
from .derive import derive, pretty
from .expr import ParseError, Program, parse, to_text
from .extract import Extraction, extract
from .layout import Layout, LayoutError, layout
from .logic import AND, AND3, BUF, GATES, NAND, NOR, NOT, OR, XOR, Gate, Logic, truth_table
from .netlist import GateInstance, Netlist
from .placement import auto_place
from .routing import RoutedWire, route
from .schematic import Port, Schematic, Symbol
