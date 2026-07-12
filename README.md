# Agent-Friendly Hardware Spec Converter

[![Repository](https://img.shields.io/badge/GitHub-Ollama_Hardware_documentation-blue)](https://github.com/harshalDharpure/Ollama_Hardware_documentation)

Hackathon solution for **Silicon Design Domain — Challenge 3**: convert hardware specification documents (PDF, Word, plain text) into structured, machine-consumable formats for AI agents.

**Repository:** https://github.com/harshalDharpure/Ollama_Hardware_documentation

## Features

- **Input formats:** PDF, DOCX, TXT/MD
- **Datasheet mode (default):** DS3231-style IC datasheets → hackathon deliverables
  - `structured_specification.md`, `canonical_spec.json`
  - Architecture / data-flow / dependency Mermaid diagrams
  - `electrical_characteristics.csv`, `relationships.csv`, `extraction_report.json`
- **RTL spec mode:** VeriGraphi-style module decomposition for processor/SoC specs
- **Pipeline (research-backed):**
  - **VeriGraphi** — multi-agent spec analysis (Summarizer → Decomposer → Specifier → Auditor)
  - **NSC (Enhance)** — YOLO/heuristic detection → key-point labeling → Hough connectivity → VLM Mermaid
  - **OmniSch** — PaddleOCR + spatial netlist + agentic crop/zoom + deterministic netlist→Mermaid
  - Vision LLM block-diagram extraction for IC functional diagrams
  - Table normalizer for electrical parameter extraction
- **100% local inference** via [Ollama](https://ollama.com)

## Quick Start

### 1. Install Ollama and pull models

```bash
ollama pull qwen2.5:7b
ollama pull llava:7b
```

### 2. Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 3. Download YOLO weights (optional, for schematic pages)

```bash
./scripts/download_yolo_weights.sh
```

### 4. Run the Streamlit app

```bash
python -m streamlit run app.py
```

Open http://localhost:8501, upload a datasheet PDF, and click **Run Pipeline**.

### 5. Reference output

See `sample/` for the expected DS3231 hackathon deliverable quality. Sample PDF: `data/samples/ds3231.pdf`.

## Project Structure

```
app.py                 # Streamlit UI
config/default.yaml    # Ollama and pipeline settings
sample/                # Reference DS3231 hackathon outputs
models/                # Schematic YOLO weights (download script included)
scripts/               # Utility scripts
src/
  ingestion/           # PDF/DOCX/TXT loaders + table normalizer
  agents/              # LLM agents + datasheet synthesizer
  diagram/             # NSC, OmniSch, block diagram, YOLO, OCR pipelines
  graph/               # HDA knowledge graph
  output/              # Markdown, Mermaid sanitizer, ZIP export
  pipeline.py          # End-to-end orchestration
data/samples/          # Development specifications
data/output/           # Generated artifacts (gitignored)
```

## Configuration

Edit `config/default.yaml`:

```yaml
pipeline:
  mode: datasheet          # datasheet | rtl_spec
  omnish_enabled: true

ollama:
  base_url: "http://localhost:11434"
  text_model: "qwen2.5:7b"
  vision_model: "llava:7b"

diagram:
  yolo_weights: "models/schematic_yolov8.pt"
  yolo_device: "cpu"
  dense_symbol_threshold: 40
```

## Research References

| Paper | Contribution used |
|-------|-------------------|
| VeriGraphi | Multi-agent spec analysis, HDA knowledge graph |
| Enhance (NSC) | Key-point labeling + VLM Mermaid for diagrams |
| OmniSch | OCR, spatial netlist, agentic visual search |

## Tests

```bash
python -m pytest tests/ -v
```

## License

Hackathon project — use and modify freely.
