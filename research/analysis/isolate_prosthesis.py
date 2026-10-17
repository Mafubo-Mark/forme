"""Extract the test4 shank within a reviewed cylinder, preserving COLMAP coordinates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement


def isolate(source: Path, settings: Path, output: Path) -> dict:
    cfg = json.loads(settings.read_text())
    origin = np.asarray(cfg["origin_colmap"], dtype=float)
    axis = np.asarray(cfg["axis_colmap"], dtype=float)
    axis /= np.linalg.norm(axis)
    start, end = map(float, cfg["axis_range_colmap"])
    radius = float(cfg["radius_colmap"])
    cloud = PlyData.read(str(source))
    vertices = cloud["vertex"].data
    xyz = np.column_stack([vertices[k] for k in ("x", "y", "z")])
    offset = xyz - origin
    axial = offset @ axis
    radial = np.linalg.norm(offset - np.outer(axial, axis), axis=1)
    keep = np.isfinite(xyz).all(axis=1) & (axial >= start) & (axial <= end) & (radial <= radius)
    if keep.sum() < 1500:
        raise ValueError(f"Only {keep.sum()} points remain; inspect the axis and limits")
    selected = np.asarray(vertices[keep])
    output.parent.mkdir(parents=True, exist_ok=True)
    PlyData([PlyElement.describe(selected, "vertex")], text=False).write(str(output))
    result = {
        "source": str(source.resolve()), "output": str(output.resolve()),
        "source_points": len(vertices), "selected_points": int(keep.sum()),
        "axis_range_colmap": [start, end], "radius_colmap": radius,
        "selected_xyz_p01_p50_p99": np.percentile(xyz[keep], [1, 50, 99], axis=0).tolist(),
        "selected_axial_p01_p99": np.percentile(axial[keep], [1, 99]).tolist(),
        "selected_radial_p50_p99": np.percentile(radial[keep], [50, 99]).tolist(),
        "warning": "This is a geometric crop, not a verified segmentation. Review the cloud for background points, gaps, and bolt geometry.",
    }
    output.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("settings", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(isolate(args.source, args.settings, args.output), indent=2))
