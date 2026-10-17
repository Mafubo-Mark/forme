#!/bin/zsh
# Rebuild test4 appearance 3DGS only. Automatic CAD is paused after audit.
set -eu
BASE=/Volumes/extra/workspace1
CASE="$BASE/projects/test4"
PY="$BASE/apps/drawing-with-gaussians/.venv/bin/python"
export TMPDIR="$BASE/app-data/tmp"
export PYTHONPATH="$BASE/apps/FreeCAD.app/Contents/Resources/lib"
export FREECAD_USER_HOME="$BASE/app-data/freecad"
export FREECAD_USER_DATA="$BASE/app-data/freecad"
export XDG_CONFIG_HOME="$BASE/app-data/config"
export XDG_DATA_HOME="$BASE/app-data/data"
export XDG_CACHE_HOME="$BASE/app-data/cache"
mkdir -p "$TMPDIR" "$CASE/gs-experiment/run-alpha-5000"
"$PY" "$CASE/gs-experiment/prepare_dataset.py"
"$BASE/apps/brush-v0.3.0/brush_app" "$CASE/gs-experiment/dataset-alpha" \
  --total-steps 5000 --eval-split-every 8 --eval-every 1000 \
  --export-every 1000 --export-path "$CASE/gs-experiment/run-alpha-5000" \
  --max-resolution 1600 --max-splats 500000 --eval-save-to-disk
print -r -- "3DGS: $CASE/gs-experiment/run-alpha-5000/export_5000.ply"
print -r -- "Automatic CAD paused: derived masks are not independent geometry evidence."
print -r -- "Review: $CASE/gs-experiment/PIPELINE_AUDIT.md"
