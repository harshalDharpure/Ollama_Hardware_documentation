"""Convert spatial netlists into block-diagram evidence for the synthesizer."""

from __future__ import annotations

from src.models import (
    BlockComponent,
    BlockDiagramEvidence,
    BlockRelationship,
    ExternalSignal,
    SpatialNetlist,
    SymbolInstance,
)


def netlist_to_block_evidence(netlist: SpatialNetlist) -> BlockDiagramEvidence:
    sym_by_id = {s.id: s for s in netlist.symbols}
    components: list[BlockComponent] = []
    signals: list[ExternalSignal] = []

    for sym in netlist.symbols:
        if sym.symbol_type == "text_anchor" and len(sym.name) <= 10:
            signals.append(
                ExternalSignal(name=sym.name, direction="bidirectional", function="net label")
            )
        elif sym.symbol_type == "component":
            components.append(
                BlockComponent(id=sym.id, name=sym.name, type=sym.symbol_type)
            )

    relationships: list[BlockRelationship] = []
    for net in netlist.nets:
        src = sym_by_id.get(net.source_id)
        dst = sym_by_id.get(net.target_id)
        if not src or not dst:
            continue
        relationships.append(
            BlockRelationship(
                source=_display_name(src),
                target=_display_name(dst),
                relationship=net.relationship or "connects",
                evidence=net.evidence or net.net_name,
                confidence="high" if net.spatial_weight >= 0.6 else "medium",
                source_pdf_page=netlist.page,
            )
        )

    return BlockDiagramEvidence(
        page=netlist.page,
        figure_id=netlist.figure_id,
        components=components,
        external_signals=signals,
        relationships=relationships,
        confidence=netlist.confidence,
    )


def _display_name(sym: SymbolInstance) -> str:
    return sym.name or sym.id
