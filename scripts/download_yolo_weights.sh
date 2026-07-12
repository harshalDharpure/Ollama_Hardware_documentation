#!/usr/bin/env bash
# Download circuit-schematic YOLOv8 weights (AITEE / CKnievel/aitee-dataset)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="$ROOT/models"
BASE="https://raw.githubusercontent.com/CKnievel/aitee-dataset/main/netlist-generation/models"
mkdir -p "$MODELS"
echo "Downloading schematic YOLO weights to $MODELS ..."
curl -L -o "$MODELS/schematic_yolov8_small.pt" "$BASE/small.pt"
curl -L -o "$MODELS/schematic_yolov8_nano.pt" "$BASE/nano.pt"
ln -sf schematic_yolov8_small.pt "$MODELS/schematic_yolov8.pt"
ls -lh "$MODELS"/*.pt
echo "Done. Default weights: $MODELS/schematic_yolov8.pt"
