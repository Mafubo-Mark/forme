"""Prepare a body-only point set in the existing corrected millimetre frame.

Uses the already-tested test4 axis transform and sparse-outlier criterion.
This is a geometric crop, not a semantic segmentation of the bolt or rim.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "pointcloud-contour-prototype"))
from build_partial_shell import load_points

cfg = json.loads((ROOT / "pointcloud-axis-corrected/sections.json").read_text())
cfg["source"] = str(ROOT / "colmap-retune-20261002/isolated-prosthesis-retuned.ply")
p = load_points(cfg)
input_count = len(p)
p = p[(p[:, 2] >= 10) & (p[:, 2] <= 365)]
radial = np.linalg.norm(p[:, :2], axis=1)
p = p[radial < 90]
crop_count = len(p)

# Remove isolated points within each 50 mm band, retaining 99.5% of the
# observed points even in the sparsely scanned upper region.
d12 = cKDTree(p).query(p, k=12, workers=-1)[0][:, -1]
keep = np.ones(len(p), bool)
for lo in range(10, 361, 50):
    band = (p[:, 2] >= lo) & (p[:, 2] < lo + 50)
    if band.any():
        keep[band] = d12[band] <= np.quantile(d12[band], 0.995)
p = p[keep]
filtered_count = len(p)

# Uniform 0.75 mm voxel representatives limit over-weighting densely observed
# views while retaining the physical scale of the original point cloud.
voxel = 0.75
grid = np.floor(p / voxel).astype(np.int32)
_, first = np.unique(grid, axis=0, return_index=True)
p = p[np.sort(first)]
np.savetxt(HERE / "body-points.xyz", p, fmt="%.6f")
(HERE / "input-report.json").write_text(json.dumps({
    "source": cfg["source"],
    "coordinate_frame": "test4 corrected-axis millimetres",
    "input_points": input_count,
    "z10_365_radial_under_90_points": crop_count,
    "after_bandwise_sparse_outlier_filter": filtered_count,
    "after_0_75mm_voxel_representatives": len(p),
    "limitations": ["Radial crop and density filtering can remove true small features.",
                    "Bolt and upper rim are not identified semantically.",
                    "The input contains no independent physical accuracy check."],
}, indent=2) + "\n")
print(len(p))
