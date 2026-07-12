"""Smoke tests for OmniSch spatial netlist pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.diagram.netlist_to_evidence import netlist_to_block_evidence
from src.diagram.netlist_to_mermaid import enrich_netlist_mermaid
from src.diagram.spatial_netlist import build_spatial_netlist, merge_spatial_netlists
from src.output.mermaid_sanitizer import is_valid_mermaid


def test_build_spatial_netlist_from_sample_page():
    renders = ROOT / "data" / "output" / "ds3231" / "ds3231" / "page_renders"
    if not renders.exists():
        pytest.skip("page renders missing")
    page = renders / "page_1.png"
    if not page.exists():
        page = next(renders.glob("page_*.png"), None)
    if not page:
        pytest.skip("no page image")

    netlist = build_spatial_netlist("page_test", page, page=1)
    assert netlist.figure_id == "page_test"
    assert netlist.pipeline == "omnish"


def test_netlist_mermaid_is_valid():
    from src.models import BoundingBox, NetEdge, SpatialNetlist, SymbolInstance

    netlist = SpatialNetlist(
        figure_id="test",
        symbols=[
            SymbolInstance(
                id="vcc",
                name="VCC",
                symbol_type="text_anchor",
                bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10),
            ),
            SymbolInstance(
                id="power_control",
                name="Power Control",
                symbol_type="component",
                bbox=BoundingBox(x1=20, y1=0, x2=40, y2=10),
            ),
        ],
        nets=[
            NetEdge(source_id="vcc", target_id="power_control", relationship="powers"),
        ],
        confidence=0.8,
    )
    netlist = enrich_netlist_mermaid(netlist)
    assert netlist.mermaid_architecture
    assert is_valid_mermaid(netlist.mermaid_architecture)
    evidence = netlist_to_block_evidence(netlist)
    assert evidence.components or evidence.relationships


def test_resolve_yolo_weights():
    from src.diagram.yolo_detector import resolve_yolo_weights

    path = resolve_yolo_weights("models/schematic_yolov8.pt")
    if not path or not Path(path).exists():
        pytest.skip("YOLO weights not downloaded")
    assert path.endswith(".pt")


def test_merge_spatial_netlists():
    from src.models import SpatialNetlist, SymbolInstance, BoundingBox

    a = SpatialNetlist(
        figure_id="a",
        symbols=[SymbolInstance(id="osc", name="Oscillator", symbol_type="component", bbox=BoundingBox())],
        confidence=0.7,
    )
    b = SpatialNetlist(
        figure_id="b",
        symbols=[SymbolInstance(id="i2c", name="I2C", symbol_type="component", bbox=BoundingBox())],
        confidence=0.8,
    )
    merged = merge_spatial_netlists([a, b])
    assert len(merged.symbols) == 2
