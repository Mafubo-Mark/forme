"""Keep the main CGAL component, apply standard Taubin smoothing, export meshes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "pointcloud-contour-prototype"))
from build_partial_shell import load_points

results = {}
for stem in ("alpha4-offset0p5", "alpha4-offset1p5", "alpha8-offset2"):
    raw = trimesh.load_mesh(HERE / f"{stem}.off", process=False)
    main = max(raw.split(only_watertight=False), key=lambda c: len(c.faces))
    main.export(HERE / f"{stem}-main.off")
    smoothed = main.copy()
    trimesh.smoothing.filter_taubin(smoothed, lamb=0.5, nu=0.52, iterations=10)
    smoothed.export(HERE / f"{stem}-smooth.off")
    smoothed.export(HERE / f"{stem}-smooth.stl")
    delta = np.linalg.norm(smoothed.vertices - main.vertices, axis=1)
    results[stem] = {
        "original_components": len(raw.split(only_watertight=False)),
        "main_vertices": len(main.vertices), "main_faces": len(main.faces),
        "main_watertight": bool(main.is_watertight),
        "smooth_watertight": bool(smoothed.is_watertight),
        "smooth_vertex_shift_mm_median": round(float(np.median(delta)), 3),
        "smooth_vertex_shift_mm_p90": round(float(np.percentile(delta, 90)), 3),
        "smooth_vertex_shift_mm_max": round(float(delta.max()), 3),
        "smooth_bounds_mm": smoothed.bounds.tolist(),
    }

cfg = json.loads((ROOT / "pointcloud-axis-corrected/sections.json").read_text())
cfg["source"] = str(ROOT / "colmap-retune-20261002/isolated-prosthesis-retuned.ply")
points = load_points(cfg)
points = points[(points[:, 2] >= 10) & (points[:, 2] <= 365)]
points = points[np.linalg.norm(points[:, :2], axis=1) < 90]
rng = np.random.default_rng(20261002)
queries = points[rng.choice(len(points), min(len(points), 25000), replace=False)]
np.savetxt(HERE / "evaluation-points.xyz", queries, fmt="%.6f")
results["evaluation"] = {"input_source": cfg["source"], "sampled_points": len(queries),
                         "note": "Sampled from the same reconstructed point cloud, not independent physical ground truth."}
(HERE / "mesh-build.json").write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results, indent=2))
