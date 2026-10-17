#!/usr/bin/env python3
"""Evaluation-only trial: survey an external rim prior and gently tune V2's upper body.

The public GPL model is analysed, never copied into the exported cover geometry.
Run with the project's geometry Python environment (trimesh, scipy, pycolmap, cv2).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pycolmap
import trimesh
from scipy.interpolate import PchipInterpolator


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "forme-backend/data/cover_tasks/fa5c0a40-fd4a-474f-80cf-3da92d7af3a8"
BASE = TASK / "workbuddy_hybrid_v2"
PUBLIC = ROOT / "external-priors/imperial-poi-d-25-00094"
OUT = Path(__file__).resolve().parent
OUT.mkdir(exist_ok=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def angular_top_profile(vertices: np.ndarray, radial_cols: tuple[int, int], height_col: int) -> np.ndarray:
    x, y = vertices[:, radial_cols[0]], vertices[:, radial_cols[1]]
    angle = np.mod(np.arctan2(y - np.median(y), x - np.median(x)), 2 * np.pi)
    bins = np.minimum((angle / (2 * np.pi) * 72).astype(int), 71)
    h = vertices[:, height_col]
    return np.array([np.percentile(h[bins == i], 99.9) for i in range(72)])


sources = {part: BASE / f"cover_{part}_review_candidate.stl" for part in ("front", "rear")}
base_meshes = {part: trimesh.load_mesh(path, process=True) for part, path in sources.items()}
base_vertices = np.vstack([mesh.vertices for mesh in base_meshes.values()])
base_rim = angular_top_profile(base_vertices, (0, 1), 2)
public_profiles = {}
for tag, filename in (("HOLO", "SDC-4-HOLO_Socket.stl"),
                      ("Pin_Lock", "SDC-5-Pin_Lock_Socket.stl"),
                      ("Vacuum", "SDC-6-Vacuum_Socket.stl")):
    mesh = trimesh.load_mesh(PUBLIC / filename, process=True)
    public_profiles[tag] = angular_top_profile(np.asarray(mesh.vertices), (0, 2), 1)

public_rim = public_profiles["HOLO"]
a = (base_rim - base_rim.mean()) / base_rim.std()
b = (public_rim - public_rim.mean()) / public_rim.std()
matches = [(float(np.corrcoef(a, np.roll(b[::-1] if flip else b, roll))[0, 1]), flip, roll)
           for flip in (False, True) for roll in range(72)]
best_correlation, mirror, roll = max(matches)
span_local = float(np.ptp(base_rim))
span_public = float(np.ptp(public_rim))
analysis = {
    "source": "ImperialCollegeLondon/POI-D-25-00094-SDC; three sockets based on one mock residual limb",
    "sourceLicense": "GPL-3.0",
    "publicProfileAxis": "Y long axis; 72 angular bins around X/Z; per-bin 99.9th percentile Y",
    "baseProfileAxis": "Z long axis; 72 angular bins around X/Y; per-bin 99.9th percentile Z",
    "baseRimSpanMm": round(span_local, 3),
    "publicRimSpanMm": round(span_public, 3),
    "bestNormalizedProfileCorrelation": round(best_correlation, 4),
    "bestAlignmentMirror": mirror,
    "bestAlignmentRollBins": roll,
    "otherPublicVariantMedianAbsProfileDifferenceMm": {
        tag: round(float(np.median(np.abs(profile - public_rim))), 3)
        for tag, profile in public_profiles.items() if tag != "HOLO"
    },
    "directPublicGeometryTransfer": False,
    "reason": "One mock subject, much deeper cutline; GPL geometry excluded from candidate export.",
    "files": {p.name: sha(p) for p in PUBLIC.glob("*.stl")},
}
(OUT / "source_analysis.json").write_text(json.dumps(analysis, indent=2) + "\n")


# V2 upper-body profile already follows the cloud through z=245. Apply only a
# bounded fraction of its remaining X-radius deficit where angular coverage was
# assessed, and fade to zero before the uncertain uppermost cutline.
validation = json.loads((BASE / "_build/validation.json").read_text())
band = {int(row["z"]): row for row in validation["contour"]["bands"]}
stations = np.array([240, 250, 260, 270, 280, 290, 305], float)
offsets = np.array([0, max(0, band[250]["target_outer_rx"] - band[250]["cover_outer_rx"]) * .6,
                    max(0, band[260]["target_outer_rx"] - band[260]["cover_outer_rx"]) * .6,
                    max(0, band[270]["target_outer_rx"] - band[270]["cover_outer_rx"]) * .6,
                    max(0, band[280]["target_outer_rx"] - band[280]["cover_outer_rx"]) * .6,
                    .4, 0], float)
offsets = np.clip(offsets, 0, 1.3)
offset_at = PchipInterpolator(stations, offsets, extrapolate=False)
z_rows = np.array([row["z"] for row in validation["contour"]["bands"]])
rx_rows = np.array([row["cover_outer_rx"] for row in validation["contour"]["bands"]])
# Keep the original template V2 X centre fixed in the narrow band. The fitted
# radius correction is only about 1 mm, so centroid drift is negligible here.
cx = float(np.median(base_vertices[(base_vertices[:, 2] >= 250) & (base_vertices[:, 2] <= 285), 0]))

candidate_meshes = {}
max_move = 0.0
for part, mesh in base_meshes.items():
    vertices = np.asarray(mesh.vertices).copy()
    z = vertices[:, 2]
    delta = np.nan_to_num(offset_at(z), nan=0.0)
    rx = np.interp(z, z_rows, rx_rows)
    dx = delta * (vertices[:, 0] - cx) / np.maximum(rx, 1.0)
    vertices[:, 0] += dx
    max_move = max(max_move, float(np.max(np.abs(dx))))
    candidate = trimesh.Trimesh(vertices=vertices, faces=mesh.faces, process=False)
    target = OUT / f"cover_{part}_upper_body_trial.stl"
    candidate.export(target)
    reloaded = trimesh.load_mesh(target, process=True)
    candidate_meshes[part] = reloaded
    assert reloaded.is_watertight and reloaded.is_winding_consistent
    assert len(reloaded.split(only_watertight=False)) == 1


def section_rx(meshes: dict[str, trimesh.Trimesh], z: float) -> float:
    vertices = np.vstack([m.vertices for m in meshes.values()])
    x = vertices[np.abs(vertices[:, 2] - z) < 2.5, 0]
    return float((np.percentile(x, 99.5) - np.percentile(x, .5)) / 2)


section_check = []
for z in (240, 250, 260, 270, 280, 290, 300, 320):
    target = band[z]["target_outer_rx"]
    before = section_rx(base_meshes, z)
    after = section_rx(candidate_meshes, z)
    section_check.append({"zMm": z, "targetOuterRxMm": target,
                          "beforeRxMm": round(before, 3), "afterRxMm": round(after, 3),
                          "beforeAbsErrorMm": round(abs(before - target), 3),
                          "afterAbsErrorMm": round(abs(after - target), 3)})


# Project both sets through the same COLMAP cameras. The contour is a union of
# projected vertices, not an occlusion-aware view or physical clearance test.
sec = json.loads((ROOT / "pointcloud-axis-corrected/sections.json").read_text())
cfg = json.loads((ROOT / "pointcloud-axis-corrected/config.json").read_text())
scale = json.loads((ROOT / "analysis/scale-calibration.json").read_text())["mm_per_colmap_unit"]
axis = np.asarray(cfg["axis"], float); axis /= np.linalg.norm(axis)
front_axis = np.asarray(cfg["front_vector"], float)
front_axis -= front_axis.dot(axis) * axis
Y = front_axis / np.linalg.norm(front_axis)
X = np.cross(Y, axis); X /= np.linalg.norm(X)
Y = np.cross(axis, X); Z = axis
origin = np.asarray(sec["origin_in_input_coordinates"], float)
cloud = np.asarray(trimesh.load(ROOT / "analysis/isolated-prosthesis.ply", process=False).vertices)
lo = np.percentile((cloud - origin) @ Z, float(cfg["trim_low_percent"]))
shift = lo * scale + float(cfg["cover_start_mm"])
rec = pycolmap.Reconstruction(str(ROOT / "reconstruction/dense/sparse"))


def contour(meshes: dict[str, trimesh.Trimesh], im, camera, shape) -> list[np.ndarray]:
    local = np.vstack([m.vertices for m in meshes.values()])
    world = origin + (local[:, 0, None] * X + local[:, 1, None] * Y +
                      (local[:, 2, None] + shift) * Z) / scale
    pose = np.asarray(im.cam_from_world().matrix())
    q = world @ pose[:, :3].T + pose[:, 3]
    fx, fy, px, py = camera.params[:4]
    uv = np.rint(np.column_stack((fx * q[:, 0] / q[:, 2] + px,
                                 fy * q[:, 1] / q[:, 2] + py))).astype(np.int32)
    height, width = shape[:2]
    valid = (q[:, 2] > 0) & (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
    mask = np.zeros((height, width), np.uint8)
    mask[uv[valid, 1], uv[valid, 0]] = 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8))
    curves, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [curve for curve in curves if cv2.contourArea(curve) > 1000]


for frame in (32, 40, 75):
    name = f"frame_{frame:05d}.jpg"
    im = next(image for image in rec.images.values() if image.name == name)
    camera = rec.cameras[im.camera_id]
    photo = cv2.imread(str(ROOT / "reconstruction/dense/images" / name))
    cv2.drawContours(photo, contour(base_meshes, im, camera, photo.shape), -1, (255, 0, 255), 2)
    cv2.drawContours(photo, contour(candidate_meshes, im, camera, photo.shape), -1, (255, 255, 0), 2)
    cv2.putText(photo, "Magenta V2 / Cyan bounded trial", (25, 60),
                cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 0, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(OUT / f"overlay_{frame:05d}.jpg"), photo, [cv2.IMWRITE_JPEG_QUALITY, 90])

result = {
    "status": "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED",
    "geometrySource": "WorkBuddy V2 only; no public GPL geometry transferred",
    "sourceAnalysis": "source_analysis.json",
    "adjustment": "bounded X-radius correction from existing 240-280 mm point-cloud profile residual; fade to zero by 305 mm",
    "stationsMm": stations.tolist(), "offsetsMm": np.round(offsets, 3).tolist(),
    "maxVertexMoveMm": round(max_move, 3),
    "upperRimZUnchanged": True,
    "sections": section_check,
    "meshes": {part: {"path": f"cover_{part}_upper_body_trial.stl",
                      "sha256": sha(OUT / f"cover_{part}_upper_body_trial.stl"),
                      "triangles": len(mesh.faces), "watertight": bool(mesh.is_watertight)}
               for part, mesh in candidate_meshes.items()},
    "limitations": ["public prior is a single mock specimen and not used directly",
                    "source point cloud and video share the same capture",
                    "upper rim clearance, side opening thin area, fasteners and physical fit remain unverified"],
}
(OUT / "trial_report.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"source": analysis, "trial": {k: result[k] for k in
       ("status", "maxVertexMoveMm", "stationsMm", "offsetsMm", "sections")}}, indent=2))
