"""Agent-Friendly Hardware Spec Converter - Streamlit Application."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_config
from src.diagram.yolo_detector import resolve_yolo_weights
from src.llm.ollama_client import OllamaClient, resolve_ollama_models
from src.output.mermaid_sanitizer import sanitize_mermaid
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
    safe_code = sanitize_mermaid(code)
    code_json = json.dumps(safe_code)
    diagram_html = f"""
    <html>
      <head>
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <style>
          body {{ margin: 0; padding: 8px; background: #ffffff; }}
          #diagram {{ text-align: center; }}
          #err {{ color: #b00020; font: 12px/1.4 monospace; white-space: pre-wrap; }}
        </style>
      </head>
      <body>
        <div id="diagram" class="mermaid"></div>
        <pre id="err"></pre>
        <script>
          const code = {code_json};
          mermaid.initialize({{
            startOnLoad: false,
            securityLevel: "loose",
            theme: "default",
            maxEdges: 2000
          }});
          const target = document.getElementById("diagram");
          target.textContent = code;
          mermaid.run({{ nodes: [target], suppressErrors: false }}).catch((err) => {{
            const msg = (err && (err.message || err.str || String(err))) || "Mermaid render failed";
            document.getElementById("err").textContent = msg;
          }});
        </script>
      </body>
    </html>
    """
    components.html(diagram_html, height=height, scrolling=True)
    with st.expander("Mermaid source"):
        st.code(safe_code, language="text")


def csv_to_dataframe(csv_text: str) -> pd.DataFrame:
    if not csv_text.strip():
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(csv_text))


def check_ollama(base_url: str, text_model: str, vision_model: str) -> dict:
    client = OllamaClient(base_url=base_url, text_model=text_model, vision_model=vision_model)
    return client.health_check()


def rows_to_dataframe(rows: list[list[str]]) -> pd.DataFrame:
    """Build a display-safe DataFrame from extracted table rows."""
    if not rows:
        return pd.DataFrame()

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    seen: dict[str, int] = {}
    unique_headers: list[str] = []
    for i, header in enumerate(headers):
        base = header or f"Column {i + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        unique_headers.append(base if count == 0 else f"{base} ({count + 1})")

    data_rows = rows[1:] if len(rows) > 1 else []
    width = len(unique_headers)
    normalized_rows = [
        [(row[i] if i < len(row) else "") for i in range(width)]
        for row in data_rows
    ]
    return pd.DataFrame(normalized_rows, columns=unique_headers)


# --- Sidebar ---
st.sidebar.title("Configuration")
base_url = st.sidebar.text_input("Ollama URL", value=ollama_cfg.get("base_url", "http://localhost:11434"))
text_model = st.sidebar.text_input("Text model", value=ollama_cfg.get("text_model", "qwen2.5:7b"))
vision_model = st.sidebar.text_input("Vision model", value=ollama_cfg.get("vision_model", "llava:7b"))

resolved_text, resolved_vision, available_models = resolve_ollama_models(
    base_url=base_url,
    text_model=text_model,
    vision_model=vision_model,
    text_fallback=ollama_cfg.get("text_model_fallback"),
    vision_fallback=ollama_cfg.get("vision_model_fallback"),
)
if available_models and (resolved_text != text_model or resolved_vision != vision_model):
    st.sidebar.warning(
        f"Using installed models: text={resolved_text}, vision={resolved_vision}"
    )
text_model = resolved_text
vision_model = resolved_vision
_default_yolo = resolve_yolo_weights(cfg.get("diagram", {}).get("yolo_weights")) or ""
yolo_weights = st.sidebar.text_input(
    "YOLO weights (schematic)",
    value=_default_yolo or cfg.get("diagram", {}).get("yolo_weights") or "models/schematic_yolov8.pt",
)
if _default_yolo:
    st.sidebar.caption(f"Active weights: `{Path(_default_yolo).name}`")
process_all = st.sidebar.checkbox(
    "Include legacy NSC debug diagram work",
    value=False,
)
omnish_enabled = st.sidebar.checkbox(
    "OmniSch spatial netlist pipeline (YOLO + OCR + agentic)",
    value=cfg.get("pipeline", {}).get("omnish_enabled", True),
)

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
sample_path = ROOT / "data" / "samples" / "ds3231.pdf"
use_sample = st.button("Use built-in DS3231 sample (no upload needed)", type="secondary")

save_path: Path | None = None
if uploaded:
    samples_dir = ROOT / "data" / "output" / "uploads"
    samples_dir.mkdir(parents=True, exist_ok=True)
    save_path = samples_dir / uploaded.name
    save_path.write_bytes(uploaded.getvalue())
    st.session_state.pop("use_sample_path", None)
    st.success(f"Uploaded: **{uploaded.name}** ({len(uploaded.getvalue()) / 1024:.0f} KB)")
elif use_sample and sample_path.exists():
    save_path = sample_path
    st.session_state["use_sample_path"] = str(sample_path)
    st.success(f"Using sample: **{sample_path.name}** ({sample_path.stat().st_size / 1024:.0f} KB)")
elif st.session_state.get("use_sample_path"):
    candidate = Path(st.session_state["use_sample_path"])
    if candidate.exists():
        save_path = candidate
        st.info(f"Sample loaded: **{candidate.name}**")

if save_path:

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
                    omnish_enabled=omnish_enabled,
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
        block_label = "Functional Blocks" if result.normalized_parameters else "Modules"
        m5.metric(block_label, f"{q.modules_valid}/{q.modules_total}")
        m6.metric("Completeness", f"{q.completeness_score:.0%}")

        tabs = st.tabs([
            "Overview",
            "Specification",
            "Canonical JSON",
            "Electrical CSV",
            "Relationships CSV",
            "Extraction Report",
            "All Tables",
            "Page Explorer",
            "Architecture",
            "Data Flow",
            "Dependency Graph",
            "Debug Diagrams",
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
            st.markdown("### System Architecture")
            render_mermaid(result.architecture_mermaid, height=400)
            if result.block_diagram_evidence:
                with st.expander("Block diagram evidence (semantic)"):
                    st.json([e.model_dump() for e in result.block_diagram_evidence])

        # --- Specification ---
        with tabs[1]:
            spec_md = result.structured_specification or result.markdown
            st.markdown(spec_md)
            with st.expander("Raw structured_specification.md"):
                st.code(spec_md, language="markdown")

        # --- Canonical JSON ---
        with tabs[2]:
            st.json(result.canonical_spec or {})

        # --- Electrical CSV ---
        with tabs[3]:
            elec_df = csv_to_dataframe(result.electrical_characteristics_csv)
            if elec_df.empty:
                st.info("No electrical characteristics CSV generated.")
            else:
                st.dataframe(elec_df, use_container_width=True, height=450)

        # --- Relationships CSV ---
        with tabs[4]:
            rel_df = csv_to_dataframe(result.relationships_csv)
            if rel_df.empty:
                st.info("No relationships CSV generated.")
            else:
                st.dataframe(rel_df, use_container_width=True, height=450)

        # --- Extraction Report ---
        with tabs[5]:
            st.json(result.extraction_report or {})

        # --- All Tables ---
        with tabs[6]:
            st.markdown(f"### {len(doc.tables)} Tables Extracted")
            if not doc.tables:
                st.info("No tables detected. Try a PDF with structured tables.")
            for t in doc.tables:
                with st.expander(f"**{t.caption}** — Page {t.page} ({t.row_count}×{t.col_count})", expanded=False):
                    if t.rows:
                        st.dataframe(rows_to_dataframe(t.rows), use_container_width=True)
                    st.markdown("**Markdown:**")
                    st.markdown(t.markdown)

        # --- Page Explorer ---
        with tabs[7]:
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
                        st.dataframe(rows_to_dataframe(t.rows), use_container_width=True)
                page_diagrams = [d for d in result.diagram_results if d.figure_id.startswith(f"page_{page.page_num}") or d.original_path.endswith(f"page_{page.page_num}.png")]
                if not page_diagrams:
                    page_diagrams = [d for d in result.diagram_results if f"_{page.page_num}_" in d.figure_id or d.figure_id == f"fig_{page.page_num}_0"]
                for dr in page_diagrams:
                    st.markdown(f"#### Mermaid: {dr.figure_id}")
                    render_mermaid(dr.mermaid_code, height=350)

        # --- Architecture ---
        with tabs[8]:
            st.markdown("### Architecture Diagram")
            render_mermaid(result.architecture_mermaid)
            st.code(result.architecture_mermaid, language="text")

        # --- Data Flow ---
        with tabs[9]:
            render_mermaid(result.dataflow_mermaid)
            st.code(result.dataflow_mermaid, language="text")

        # --- Dependencies ---
        with tabs[10]:
            render_mermaid(result.dependency_mermaid)
            st.code(result.dependency_mermaid, language="text")

        # --- Debug Diagrams ---
        with tabs[11]:
            st.caption("Internal NSC/J-label artifacts are debug-only and not included in hackathon deliverables.")
            if not result.diagram_results:
                st.info("No debug diagram work generated. Enable sidebar option to include debug artifacts.")
            for dr in result.diagram_results:
                with st.expander(f"{dr.figure_id} — {dr.pipeline_used}"):
                    c1, c2 = st.columns(2)
                    with c1:
                        if Path(dr.original_path).exists():
                            st.image(dr.original_path, caption="Original", use_container_width=True)
                    with c2:
                        if dr.labeled_path and Path(dr.labeled_path).exists():
                            st.image(dr.labeled_path, caption="NSC labeled (debug)", use_container_width=True)
                    st.code(dr.mermaid_code, language="text")

        # --- Knowledge Graph ---
        with tabs[12]:
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
        with tabs[13]:
            st.json(json.loads(result.quality.model_dump_json()))
            st.markdown("### Module Audit")
            for m in result.plan.modules:
                icon = "✅" if m.valid else "⚠️"
                st.write(f"{icon} **{m.name}** — {len(m.inputs)} in / {len(m.outputs)} out")
                for issue in m.audit_issues:
                    st.caption(f"  · {issue}")

        export_zip = Path(result.export_dir) / "ds3231_hackathon_output.zip"
        if not export_zip.exists():
            export_zip = Path(result.export_dir) / "spec_export.zip"
        if export_zip.exists():
            st.download_button(
                "Download Hackathon Output ZIP",
                data=export_zip.read_bytes(),
                file_name=f"{doc.title}_hackathon_output.zip",
                mime="application/zip",
            )

else:
    st.info("Upload a PDF datasheet or click **Use built-in DS3231 sample** to avoid browser upload issues.")
    if sample_path.exists():
        st.markdown("Sample DS3231 PDF is available in the project.")
