"""Compare fusion settings against the original cloud and independent photo masks.

These are diagnostic metrics, not a physical-accuracy measurement.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from plyfile import PlyData
from scipy.ndimage import binary_dilation
from scipy.spatial import cKDTree
import pycolmap

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
SCALE = 141.22180552601463
CFG = json.loads((ROOT / "analysis/isolation-config.json").read_text())
ORIGIN = np.asarray(CFG["origin_colmap"], dtype=float)
AXIS = np.asarray(CFG["axis_colmap"], dtype=float)
AXIS /= np.linalg.norm(AXIS)
START, END = CFG["axis_range_colmap"]
RADIUS = CFG["radius_colmap"]


def read_cropped(path: Path):
    v = PlyData.read(str(path))["vertex"].data
    xyz = np.column_stack([v[k] for k in ("x", "y", "z")]).astype(np.float64)
    offset = xyz - ORIGIN
    axial = offset @ AXIS
    radial_vec = offset - axial[:, None] * AXIS
    radial = np.linalg.norm(radial_vec, axis=1)
    keep = np.isfinite(xyz).all(axis=1) & (axial >= START) & (axial <= END) & (radial <= RADIUS)
    return len(v), xyz[keep], axial[keep], radial_vec[keep]


def coverage(axial, radial_vec):
    ref = np.array([1., 0., 0.])
    ref -= AXIS * (ref @ AXIS)
    ref /= np.linalg.norm(ref)
    side = np.cross(AXIS, ref)
    ang = np.mod(np.arctan2(radial_vec @ side, radial_vec @ ref), 2 * np.pi)
    ai = np.clip(((axial - START) / (END - START) * 60).astype(int), 0, 59)
    bi = np.clip((ang / (2 * np.pi) * 72).astype(int), 0, 71)
    bins = np.zeros((60, 72), np.int32)
    np.add.at(bins, (ai, bi), 1)
    return {
        "empty_bins": int(np.sum(bins == 0)),
        "bins_fewer_than_5_points": int(np.sum(bins < 5)),
        "points_by_axial_sixths": np.bincount(np.clip(ai // 10, 0, 5), minlength=6).tolist(),
        "empty_bins_by_axial_sixths": [int(np.sum(bins[i:i+10] == 0)) for i in range(0, 60, 10)],
    }


def mask_outside_fraction(xyz):
    """Fraction outside independent photo masks, after 5-pixel tolerance.

    This may flag segmentation errors or points on occluded surfaces; it is only
    a comparative outlier signal, not a ground-truth 3D error.
    """
    rng = np.random.default_rng(42)
    pts = xyz[rng.choice(len(xyz), min(len(xyz), 60000), replace=False)]
    rec = pycolmap.Reconstruction(str(ROOT / "reconstruction/dense/sparse"))
    holdout = json.loads((ROOT / "independent-silhouette/report.json").read_text())["heldout_local_iou"]
    rows = []
    for item in holdout:
        name = item["image"]
        image = next(v for v in rec.images.values() if v.name == name)
        camera = rec.cameras[image.camera_id]
        pose = image.cam_from_world()
        camera_xyz = pts @ pose.rotation.matrix().T + np.asarray(pose.translation)
        z = camera_xyz[:, 2]
        u = camera.params[0] * camera_xyz[:, 0] / z + camera.params[2]
        v = camera.params[1] * camera_xyz[:, 1] / z + camera.params[3]
        ok = (z > 0) & (u >= 0) & (v >= 0) & (u < camera.width) & (v < camera.height)
        ix, iy = u[ok].astype(int), v[ok].astype(int)
        mask = np.asarray(Image.open(ROOT / "independent-silhouette/masks" / name.replace(".jpg", ".png")).convert("L")) > 127
        mask = binary_dilation(mask, iterations=5)
        outside = ~mask[iy, ix]
        rows.append({"image": name, "projected_points": int(ok.sum()), "outside_fraction": round(float(outside.mean()), 5)})
    return {"mean_outside_fraction": round(float(np.mean([r["outside_fraction"] for r in rows])), 5), "views": rows}


def main():
    files = {
        "baseline": ROOT / "reconstruction/dense/fused.ply",
        "min3": OUT / "fused-min3.ply",
        "relaxed": OUT / "fused-relaxed.ply",
        "patch_retuned": OUT / "fused-patch-retuned.ply",
    }
    data = {name: read_cropped(path) for name, path in files.items() if path.exists()}
    original = data["baseline"][1]
    tree = cKDTree(original)
    report = {}
    for name, (full_count, xyz, axial, radial_vec) in data.items():
        row = {"full_scene_points": full_count, "subject_roi_points": len(xyz), **coverage(axial, radial_vec)}
        if name != "baseline":
            rng = np.random.default_rng(7)
            sample = xyz[rng.choice(len(xyz), min(200000, len(xyz)), replace=False)]
            dist = tree.query(sample, k=1, workers=-1)[0] * SCALE
            row["candidate_to_baseline_mm"] = {
                "median": round(float(np.median(dist)), 3),
                "p90": round(float(np.percentile(dist, 90)), 3),
                "fraction_over_2mm": round(float(np.mean(dist > 2)), 5),
                "fraction_over_5mm": round(float(np.mean(dist > 5)), 5),
            }
        row["independent_photo_mask_diagnostic"] = mask_outside_fraction(xyz)
        report[name] = row
    (OUT / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: {j: v for j, v in row.items() if j != "independent_photo_mask_diagnostic"} | {"mask_outside_mean": row["independent_photo_mask_diagnostic"]["mean_outside_fraction"]} for k, row in report.items()}, indent=2))


if __name__ == "__main__":
    main()
