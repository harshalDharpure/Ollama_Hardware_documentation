# Agent-Friendly Hardware Spec Converter

[![Repository](https://img.shields.io/badge/GitHub-Ollama_Hardware_documentation-blue)](https://github.com/harshalDharpure/Ollama_Hardware_documentation)

Hackathon solution for **Silicon Design Domain — Challenge 3**: convert hardware specification documents (PDF, Word, plain text) into structured, machine-consumable formats for AI agents.

**Repository:** https://github.com/harshalDharpure/Ollama_Hardware_documentation
## Features

- **Input formats:** PDF, DOCX, TXT/MD
- **Outputs:**
  - Structured Markdown with hierarchical module specs
  - Mermaid architecture diagram
  - Mermaid data flow diagram
  - Mermaid dependency graph
  - HDA knowledge graph (JSON)
  - ZIP export bundle
- **Pipeline (research-backed):**
  - VeriGraphi-style multi-agent spec analysis (Summarizer → Decomposer → Specifier → Auditor)
  - NSC (Near Sight Correction) diagram preprocessing: YOLO/heuristic detection → key-point labeling → Hough connectivity → VLM Mermaid
  - OmniSch-style agentic crop/zoom fallback for dense schematics
- **100% local inference** via [Ollama](https://ollama.com)

## Quick Start

### 1. Install Ollama and pull models

```bash
ollama pull qwen2.5:7b
ollama pull llava:7b    # recommended for 6GB GPU laptops (faster than llava:13b)
```

### 2. Install Python dependencies

```bash
cd Hackathon_solution
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

Optional (for OCR on dense schematics): install [Tesseract](https://github.com/tesseract-ocr/tesseract).

### 3. Run the Streamlit app

```bash
python -m streamlit run app.py
```

Open http://localhost:8501, upload a spec, and click **Run Pipeline**.

### 4. Try the sample spec

Use `data/samples/sample_riscv_spec.txt` — a simplified RV32I processor specification.

## Project Structure

```
app.py                 # Streamlit UI
config/default.yaml    # Ollama and pipeline settings
src/
  ingestion/           # PDF/DOCX/TXT loaders
  agents/              # VeriGraphi-style LLM agents
  diagram/             # NSC + agentic diagram pipeline
  graph/               # HDA knowledge graph
  output/              # Markdown, Mermaid, ZIP export
  pipeline.py          # End-to-end orchestration
data/samples/          # Development specifications
data/output/           # Generated artifacts
```

## Configuration

Edit `config/default.yaml`:

```yaml
ollama:
  base_url: "http://localhost:11434"
  text_model: "qwen2.5:7b"
  vision_model: "llava:13b"

diagram:
  yolo_weights: null          # path to custom .pt weights
  dense_symbol_threshold: 40  # switch to agentic pipeline above this
```

## Research References

| Paper | Contribution used |
|-------|-------------------|
| VeriGraphi | Multi-agent spec analysis, HDA knowledge graph |
| Enhance (NSC) | Key-point labeling + VLM Mermaid for diagrams |
| OmniSch | Agentic visual search for dense schematics |

## Evaluation Criteria Alignment

| Criterion | Implementation |
|-----------|----------------|
| Accuracy/completeness | Auditor agent + quality metrics tab |
| Markdown readability | Hierarchical module templates with I/O tables |
| Visualization correctness | KG-derived Mermaid (consistent with JSON) |
| Robustness | Unified loader for PDF/DOCX/TXT |

## Smoke Test

```bash
python -m pytest tests/test_pipeline_smoke.py -v
```

## License

Hackathon project — use and modify freely.
