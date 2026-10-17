"""Exploratory alignment of the new Hunyuan GLB to the test4 calibrated cloud.

Only upper shell and white shaft participate. The shoe and generated bolts are
excluded from registration. The output is a review candidate, never a fit mesh.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from plyfile import PlyData
from scipy.spatial import cKDTree


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rotation_fit(source: np.ndarray, target: np.ndarray, scale: float) -> tuple[np.ndarray, np.ndarray]:
    left, right = source.mean(axis=0), target.mean(axis=0)
    u, _, vt = np.linalg.svd((source - left).T @ (target - right))
    r = vt.T @ np.diag([1.0, 1.0, np.linalg.det(vt.T @ u.T)]) @ u.T
    return r, right - scale * (r @ left)


def image_overlay(path: Path, cloud: np.ndarray, rgb: np.ndarray, model: np.ndarray,
                  axes: tuple[int, int], extent: tuple[tuple[float, float], tuple[float, float]]) -> None:
    size = 1200
    image = Image.new("RGB", (size, size), (249, 249, 249))
    draw = ImageDraw.Draw(image)
    def pixel(point):
        x = int((point[axes[0]] - extent[0][0]) / (extent[0][1] - extent[0][0]) * (size - 1))
        y = size - 1 - int((point[axes[1]] - extent[1][0]) / (extent[1][1] - extent[1][0]) * (size - 1))
        return x, y
    for point, color in zip(cloud[::2], rgb[::2]):
        x, y = pixel(point)
        if 0 <= x < size and 0 <= y < size:
            draw.point((x, y), fill=tuple(int(.6 * c + 95) for c in color))
    for point in model[::2]:
        x, y = pixel(point)
        if 0 <= x < size and 0 <= y < size:
            draw.point((x, y), fill=(210, 15, 150))
    draw.text((16, 16), "COLMAP cloud vs new Hunyuan candidate; scale/registration not verified", fill=(0, 0, 0))
    image.save(path)


def run(model_path: Path, cloud_path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261004)
    mesh = trimesh.load(model_path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError("Hunyuan GLB contains no triangle mesh")
    vertices = np.asarray(mesh.vertices)
    # Hunyuan GLB is Y-up; COLMAP analysis uses Z-up.
    upright = vertices[:, [0, 2, 1]]
    top = vertices[(vertices[:, 1] >= .94) & (vertices[:, 1] < 1.10)]
    shaft = vertices[(vertices[:, 1] >= .48) & (vertices[:, 1] < .60)]
    if len(top) < 100 or len(shaft) < 100:
        raise ValueError("Expected upper opening and shaft bands were not found")
    upper_span = float(np.quantile(top[:, 0], .99) - np.quantile(top[:, 0], .01))
    shaft_span = float(np.quantile(shaft[:, 0], .99) - np.quantile(shaft[:, 0], .01))
    scale = 120.0 / upper_span

    ply = PlyData.read(str(cloud_path))["vertex"]
    cloud = np.stack([ply[name] for name in ("x", "y", "z")], axis=1).astype(float)
    rgb = np.stack([ply[name] for name in ("red", "green", "blue")], axis=1)
    depth = -cloud[:, 2]
    gray = rgb.mean(axis=1)
    radius = np.linalg.norm(cloud[:, :2], axis=1)
    observed = {
        "white": cloud[(depth >= 192) & (depth < 311) & (gray >= 120) & (radius < 78)],
        "black": cloud[(depth >= -58) & (depth < 155) & (gray <= 100) & (radius < 90)],
    }
    if min(map(len, observed.values())) < 1000:
        raise ValueError("Reference cloud lacks enough trusted-region points")
    sampled, _ = trimesh.sample.sample_surface(mesh, 180000, seed=20261004)
    model = {
        "white": sampled[(sampled[:, 1] >= .44) & (sampled[:, 1] < .66)][:, [0, 2, 1]],
        "black": sampled[(sampled[:, 1] >= .72) & (sampled[:, 1] < 1.10)][:, [0, 2, 1]],
    }
    if min(map(len, model.values())) < 1000:
        raise ValueError("Hunyuan candidate lacks enough upper-region surface samples")
    model["white"] = model["white"][rng.choice(len(model["white"]), min(25000, len(model["white"])), replace=False)]
    model["black"] = model["black"][rng.choice(len(model["black"]), min(30000, len(model["black"])), replace=False)]
    white_fit = observed["white"][rng.choice(len(observed["white"]), min(7000, len(observed["white"])), replace=False)]
    black_fit = observed["black"][rng.choice(len(observed["black"]), min(7000, len(observed["black"])), replace=False)]

    def transformed(points, r, v):
        return scale * (points @ r.T) + v

    candidates = []
    for yaw_deg in range(0, 360, 30):
        yaw = np.deg2rad(yaw_deg)
        r = np.array([[np.cos(yaw), -np.sin(yaw), 0],
                      [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]], float)
        v = np.median(white_fit, axis=0) - scale * (r @ np.median(model["white"], axis=0))
        v[2] = -180.0 - scale * .68
        for _ in range(18):
            tree = cKDTree(transformed(model["white"], r, v))
            distances, indices = tree.query(white_fit, workers=-1)
            keep = distances <= np.quantile(distances, .78)
            trial_r, trial_v = rotation_fit(model["white"][indices[keep]], white_fit[keep], scale)
            if np.degrees(np.arccos(np.clip(trial_r[2, 2], -1, 1))) > 23:
                break
            r, v = trial_r, trial_v
            v[2] = -180.0 - scale * (r @ np.array([0, 0, .68]))[2]
        white_distance = cKDTree(transformed(model["white"], r, v)).query(white_fit, workers=-1)[0]
        black_distance = cKDTree(transformed(model["black"], r, v)).query(black_fit, workers=-1)[0]
        candidates.append({"yawSeedDeg": yaw_deg, "R": r.tolist(), "translationMm": v.tolist(),
                           "whiteMedianMm": float(np.median(white_distance)),
                           "whiteP90Mm": float(np.quantile(white_distance, .9)),
                           "blackMedianMm": float(np.median(black_distance)),
                           "blackP90Mm": float(np.quantile(black_distance, .9))})
    best = min(candidates, key=lambda c: c["whiteMedianMm"] + .2 * c["whiteP90Mm"] + .2 * c["blackMedianMm"])
    r, v = np.asarray(best["R"]), np.asarray(best["translationMm"])
    upper_points = np.concatenate([model["white"], model["black"]])
    transformed_upper = transformed(upper_points, r, v)
    image_overlay(output / "overlay_front.png", cloud, rgb, transformed_upper, (0, 2), ((-140, 140), (-355, 100)))
    image_overlay(output / "overlay_side.png", cloud, rgb, transformed_upper, (1, 2), ((-140, 140), (-355, 100)))
    # Full shoe-inclusive mesh is saved for inspection, not for cover adaptation.
    aligned = mesh.copy()
    aligned.vertices = transformed(upright, r, v)
    aligned.export(output / "hunyuan_aligned_candidate_mm.glb")
    report = {
        "status": "exploratory_alignment_review_required",
        "sourceModel": str(model_path.resolve()), "sourceModelSha256": sha256(model_path),
        "referenceCloud": str(cloud_path.resolve()), "referenceCloudSha256": sha256(cloud_path),
        "physicalTopOuterWidthMm": 120.0, "topBandY": [.94, 1.10],
        "modelTopOuterXSpanUnits": upper_span, "scaleMmPerModelUnit": scale,
        "physicalShaftOuterWidthMm": 80.0, "shaftBandY": [.48, .60],
        "modelShaftXSpanUnits": shaft_span, "derivedShaftWidthMm": shaft_span * scale,
        "independentWidthDifferenceMm": shaft_span * scale - 80.0,
        "best": best, "candidates": candidates,
        "referenceRegions": {name: len(points) for name, points in observed.items()},
        "warnings": [
            "The 120 mm and 80 mm physical landmark definitions are not independently confirmed against the new mesh.",
            "COLMAP point cloud has missing surfaces and noise; nearest distances are not fit clearances.",
            "The aligned mesh still contains shoe and synthetic fastener geometry.",
            "No template coordinate registration or manufacturing fit is verified.",
        ],
    }
    (output / "alignment_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("cloud", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = run(args.model, args.cloud, args.output)
    print(json.dumps({"status": result["status"], "scale": result["scaleMmPerModelUnit"],
                      "shaftWidthMm": result["derivedShaftWidthMm"], "best": result["best"]}, ensure_ascii=False))
