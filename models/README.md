# Schematic YOLO Weights

Circuit-specific YOLOv8 weights for OmniSch / NSC symbol detection.

## Files

| File | Size | Use |
|------|------|-----|
| `schematic_yolov8.pt` | symlink → small | **Default** (best speed/accuracy balance) |
| `schematic_yolov8_small.pt` | ~19 MB | Recommended |
| `schematic_yolov8_nano.pt` | ~5 MB | Faster, lower accuracy |

## Source

Weights from [CKnievel/aitee-dataset](https://github.com/CKnievel/aitee-dataset) (AITEE circuit netlist pipeline).

**Classes detected:** resistor (R), voltage (V), current (I), ground (GND), edges (E), probes (p), and identifier labels.

## Re-download

```bash
./scripts/download_yolo_weights.sh
```

## Config

Set in `config/default.yaml`:

```yaml
diagram:
  yolo_weights: "models/schematic_yolov8.pt"
  yolo_device: "cpu"
```

Or paste the path in the Streamlit sidebar **YOLO weights** field.

## Note

These weights target **analog circuit schematics**, not IC block diagrams. For DS3231 functional block pages, vision LLM extraction remains primary; YOLO adds symbol grounding on schematic-like pages.
