"""Agent-Friendly Hardware Spec Converter - Streamlit Application."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_config
from src.llm.ollama_client import OllamaClient
from src.pipeline import run_pipeline

st.set_page_config(
    page_title="Hardware Spec Converter",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

cfg = get_config()
ollama_cfg = cfg.get("ollama", {})


def render_mermaid(code: str, height: int = 450) -> None:
    if not code or not code.strip():
        st.info("No diagram generated.")
        return
    try:
        from streamlit_mermaid import st_mermaid
        st_mermaid(code, height=height)
    except ImportError:
        st.code(code, language="text")
        st.caption("Copy to https://mermaid.live for preview")


def check_ollama(base_url: str, text_model: str, vision_model: str) -> dict:
    client = OllamaClient(base_url=base_url, text_model=text_model, vision_model=vision_model)
    return client.health_check()


# --- Sidebar ---
st.sidebar.title("Configuration")
base_url = st.sidebar.text_input("Ollama URL", value=ollama_cfg.get("base_url", "http://localhost:11434"))
text_model = st.sidebar.text_input("Text model", value=ollama_cfg.get("text_model", "qwen2.5:7b"))
vision_model = st.sidebar.text_input("Vision model", value=ollama_cfg.get("vision_model", "llava:13b"))
yolo_weights = st.sidebar.text_input("YOLO weights (optional)", value=cfg.get("diagram", {}).get("yolo_weights") or "")
process_all = st.sidebar.checkbox("Process all diagram pages (slower, more complete)", value=True)

if st.sidebar.button("Check Ollama"):
    health = check_ollama(base_url, text_model, vision_model)
    if health.get("ok"):
        st.sidebar.success("Ollama connected")
        st.sidebar.write(f"Models: {', '.join(health.get('models', []))}")
    else:
        st.sidebar.error(f"Ollama unavailable: {health.get('error', 'unknown')}")

st.title("Agent-Friendly Hardware Spec Converter")
st.caption(
    "Full page-by-page PDF scan · All tables · Architecture / Dataflow / Dependency Mermaid · Knowledge Graph"
)

uploaded = st.file_uploader("Upload specification (PDF recommended for datasheets)", type=["pdf", "docx", "txt", "md"])

if uploaded:
    samples_dir = ROOT / "data" / "output" / "uploads"
    samples_dir.mkdir(parents=True, exist_ok=True)
    save_path = samples_dir / uploaded.name
    save_path.write_bytes(uploaded.getvalue())
    st.success(f"Uploaded: **{uploaded.name}** ({len(uploaded.getvalue()) / 1024:.0f} KB)")

    run_btn = st.button("Run Full Pipeline", type="primary")

    if run_btn:
        progress_bar = st.progress(0)
        status = st.empty()

        def on_progress(msg: str, pct: float) -> None:
            progress_bar.progress(min(pct, 1.0))
            status.text(msg)

        with st.spinner("Scanning document page-by-page and extracting all content..."):
            try:
                result = run_pipeline(
                    save_path,
                    work_dir=ROOT / "data" / "output",
                    progress_callback=on_progress,
                    ollama_base_url=base_url,
                    text_model=text_model,
                    vision_model=vision_model,
                    yolo_weights=yolo_weights or None,
                    process_all_diagrams=process_all,
                )
                st.session_state["pipeline_result"] = result
                st.session_state["pipeline_ok"] = True
            except Exception as exc:
                st.session_state["pipeline_ok"] = False
                st.error(f"Pipeline failed: {exc}")
                st.exception(exc)

    if st.session_state.get("pipeline_ok") and "pipeline_result" in st.session_state:
        result = st.session_state["pipeline_result"]
        doc = result.document
        q = result.quality

        st.divider()
        st.subheader("Extraction Summary")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Pages", q.pages_processed or len(doc.pages))
        m2.metric("Tables", q.tables_extracted or len(doc.tables))
        m3.metric("Figures", q.figures_extracted or len(doc.figures))
        m4.metric("Mermaid Diagrams", q.diagrams_generated)
        m5.metric("Modules", f"{q.modules_valid}/{q.modules_total}")
        m6.metric("Completeness", f"{q.completeness_score:.0%}")

        tabs = st.tabs([
            "Overview",
            "Structured Markdown",
            "All Tables",
            "Page Explorer",
            "Architecture",
            "Data Flow",
            "Dependencies",
            "All Diagrams",
            "Knowledge Graph",
            "Quality Report",
        ])

        # --- Overview ---
        with tabs[0]:
            st.markdown("### Document Structure")
            if doc.pages:
                page_df = pd.DataFrame([
                    {
                        "Page": p.page_num,
                        "Characters": p.char_count,
                        "Tables": p.table_count,
                        "Embedded Figures": p.figure_count,
                        "Diagram Page": p.is_diagram_page,
                    }
                    for p in doc.pages
                ])
                st.dataframe(page_df, use_container_width=True, height=350)
            st.markdown("### Combined Architecture (from all diagrams)")
            render_mermaid(result.combined_diagram_mermaid, height=500)
            st.markdown("### System Architecture (from spec text)")
            render_mermaid(result.architecture_mermaid, height=400)

        # --- Markdown ---
        with tabs[1]:
            st.markdown(result.markdown)
            with st.expander("Raw Markdown source"):
                st.code(result.markdown, language="markdown")

        # --- All Tables ---
        with tabs[2]:
            st.markdown(f"### {len(doc.tables)} Tables Extracted")
            if not doc.tables:
                st.info("No tables detected. Try a PDF with structured tables.")
            for t in doc.tables:
                with st.expander(f"**{t.caption}** — Page {t.page} ({t.row_count}×{t.col_count})", expanded=False):
                    if t.rows:
                        st.dataframe(pd.DataFrame(t.rows[1:], columns=t.rows[0] if t.rows else None), use_container_width=True)
                    st.markdown("**Markdown:**")
                    st.markdown(t.markdown)

        # --- Page Explorer ---
        with tabs[3]:
            st.markdown("### Page-by-Page Scan")
            page_nums = [p.page_num for p in doc.pages] or [1]
            selected = st.selectbox("Select page", page_nums)
            page = next((p for p in doc.pages if p.page_num == selected), None)
            if page:
                col_img, col_txt = st.columns([1, 1])
                with col_img:
                    if page.render_path and Path(page.render_path).exists():
                        st.image(page.render_path, caption=f"Page {page.page_num} render", use_container_width=True)
                    page_figs = [f for f in doc.figures if f.page == page.page_num]
                    for f in page_figs:
                        if Path(f.path).exists():
                            st.image(f.path, caption=f"{f.id} ({f.source_type})", use_container_width=True)
                with col_txt:
                    st.markdown(f"**Characters:** {page.char_count} | **Tables:** {page.table_count} | **Diagram page:** {page.is_diagram_page}")
                    st.text_area("Page text", page.text, height=400)
                page_tables = [t for t in doc.tables if t.page == page.page_num]
                if page_tables:
                    st.markdown("#### Tables on this page")
                    for t in page_tables:
                        st.markdown(f"**{t.id}**")
                        st.dataframe(pd.DataFrame(t.rows[1:], columns=t.rows[0] if t.rows else None), use_container_width=True)
                page_diagrams = [d for d in result.diagram_results if d.figure_id.startswith(f"page_{page.page_num}") or d.original_path.endswith(f"page_{page.page_num}.png")]
                if not page_diagrams:
                    page_diagrams = [d for d in result.diagram_results if f"_{page.page_num}_" in d.figure_id or d.figure_id == f"fig_{page.page_num}_0"]
                for dr in page_diagrams:
                    st.markdown(f"#### Mermaid: {dr.figure_id}")
                    render_mermaid(dr.mermaid_code, height=350)

        # --- Architecture ---
        with tabs[4]:
            st.markdown("### Architecture Diagram (from module hierarchy)")
            render_mermaid(result.architecture_mermaid)
            st.code(result.architecture_mermaid, language="text")
            st.markdown("### Combined Diagram Architecture (from all figure analysis)")
            render_mermaid(result.combined_diagram_mermaid)
            st.code(result.combined_diagram_mermaid, language="text")

        # --- Data Flow ---
        with tabs[5]:
            render_mermaid(result.dataflow_mermaid)
            st.code(result.dataflow_mermaid, language="text")

        # --- Dependencies ---
        with tabs[6]:
            render_mermaid(result.dependency_mermaid)
            st.code(result.dependency_mermaid, language="text")

        # --- All Diagrams ---
        with tabs[7]:
            if not result.diagram_results:
                st.info("No diagrams processed.")
            for dr in result.diagram_results:
                st.markdown(f"## {dr.figure_id} — `{dr.pipeline_used}` (confidence {dr.confidence:.0%})")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.caption("Original")
                    if Path(dr.original_path).exists():
                        st.image(dr.original_path, use_container_width=True)
                with c2:
                    st.caption("NSC Labeled")
                    if dr.labeled_path and Path(dr.labeled_path).exists():
                        st.image(dr.labeled_path, use_container_width=True)
                with c3:
                    st.caption("Mermaid Preview")
                    render_mermaid(dr.mermaid_code, height=280)
                st.code(dr.mermaid_code, language="text")
                st.divider()

        # --- Knowledge Graph ---
        with tabs[8]:
            st.json(json.loads(result.knowledge_graph.model_dump_json()))
            try:
                import networkx as nx
                from pyvis.network import Network

                g = nx.DiGraph()
                for node in result.knowledge_graph.nodes:
                    g.add_node(node.id, label=node.label or node.id, title=node.type)
                for edge in result.knowledge_graph.edges:
                    g.add_edge(edge.from_node, edge.to_node, title=edge.type)
                net = Network(height="550px", width="100%", directed=True)
                net.from_nx(g)
                html_path = Path(result.export_dir) / "kg_graph.html"
                net.save_graph(str(html_path))
                st.components.v1.html(html_path.read_text(encoding="utf-8"), height=570, scrolling=True)
            except Exception as exc:
                st.caption(f"Interactive graph: {exc}")

        # --- Quality ---
        with tabs[9]:
            st.json(json.loads(result.quality.model_dump_json()))
            st.markdown("### Module Audit")
            for m in result.plan.modules:
                icon = "✅" if m.valid else "⚠️"
                st.write(f"{icon} **{m.name}** — {len(m.inputs)} in / {len(m.outputs)} out")
                for issue in m.audit_issues:
                    st.caption(f"  · {issue}")

        export_zip = Path(result.export_dir) / "spec_export.zip"
        if export_zip.exists():
            st.download_button(
                "Download Full ZIP Export (Markdown + Tables + Mermaid + JSON)",
                data=export_zip.read_bytes(),
                file_name=f"{doc.title}_spec_export.zip",
                mime="application/zip",
            )

else:
    st.info("Upload a PDF datasheet (e.g. DS3231) to extract all pages, tables, and diagrams.")
    ds_sample = ROOT / "data" / "samples" / "ds3231.pdf"
    if ds_sample.exists():
        st.markdown("Sample DS3231 PDF found in project.")
