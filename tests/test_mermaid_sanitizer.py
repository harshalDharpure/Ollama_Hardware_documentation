"""Tests for Mermaid sanitization."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.output.mermaid_sanitizer import cap_mermaid_edges, count_mermaid_edges, sanitize_mermaid

BROKEN_ARCHITECTURE = (
    'flowchart LR subgraph External["External Signals"] VCC[VCC] end subgraph CHIP["DS3231 Real-Time Clock"] '
    "clock[Clock] i2c_interface[I2C Interface] power_control[Power Control] "
    "clock_and_calendar[Clock & Calendar Registers] temperature_sensor[Temperature sensor] "
    "clock_and_calendar_registers[Clock and Calendar Registers] VCC --> power_control clock --> i2c_interface "
    "i2c_interface --> clock_and_calendar Registers clock_and_calendarRegisters --> i2c_interface "
    "i2c_interface --> temperature_sensor"
)

BROKEN_DEPENDENCY = (
    'graph TD;\nVCC("powers") --> Power_Control\n'
    'Clock("provides_1hz_tick") --> I2C_Interface;'
)

BROKEN_DATAFLOW = """VCC --> powers__power_control
power_control --> powers__i2c_interface
clock_and_calendar_registers --> reads_writes__i2c_interface
I2_C_data --> reads_writes__i2c_interface
i2c_interface --> provides_1hz_tick__clock_and_calendar_registers"""


def test_collapsed_architecture_becomes_multiline():
    out = sanitize_mermaid(BROKEN_ARCHITECTURE)
    assert out.startswith("flowchart LR\n")
    assert out.count("\n") >= 6
    assert '&amp;' not in out
    assert '["Clock & Calendar Registers"]' in out or "Clock & Calendar" in out
    assert "clock_and_calendar Registers" not in out
    assert "clock_and_calendarRegisters" not in out


def test_dependency_relationship_labels_become_edge_labels():
    out = sanitize_mermaid(BROKEN_DEPENDENCY)
    assert out.startswith("graph TD\n")
    assert 'VCC("powers")' not in out
    assert '|"powers"|' in out or "powers" in out
    assert ";" not in out


def test_headerless_relationship_edges_are_repaired():
    out = sanitize_mermaid(BROKEN_DATAFLOW)
    assert out.startswith("flowchart LR\n")
    assert "__" not in out
    assert '|"powers"|' in out
    assert '|"reads_writes"|' in out
    assert "power_control" in out


def test_sample_architecture_stays_valid():
    sample = (ROOT / "sample" / "architecture.mmd").read_text(encoding="utf-8")
    out = sanitize_mermaid(sample)
    assert out.startswith("flowchart LR")
    assert "Power Control" in out
    assert "subgraph" in out.lower()


def test_cap_mermaid_edges_limits_dense_graphs():
    dense = "flowchart LR\n" + "\n".join(f"    A{i} --> B{i}" for i in range(120))
    assert count_mermaid_edges(dense) == 120
    capped = cap_mermaid_edges(dense, max_edges=40)
    assert count_mermaid_edges(capped) == 40
