"""Triangulate a reviewed ruler from current COLMAP cameras and image clicks.

Run in a geometry Python with numpy and pycolmap. Observations JSON contains
{"images": [{"name": "frame_0001.jpg", "A": [x,y], "B": [x,y]}, ...]}.
Coordinates must refer to the exact images used by the supplied COLMAP model.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pycolmap


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def point_from_rays(rows: list[dict]) -> np.ndarray:
    identity = np.eye(3)
    matrix = sum((identity - np.outer(row["ray"], row["ray"]) for row in rows), np.zeros((3, 3)))
    right = sum(((identity - np.outer(row["ray"], row["ray"])) @ row["center"] for row in rows), np.zeros(3))
    if np.linalg.cond(matrix) > 1e6:
        raise ValueError("RULER_RAYS_NEAR_PARALLEL")
    return np.linalg.solve(matrix, right)


def pixel_error(point: np.ndarray, row: dict) -> float:
    q = row["pose"][:, :3] @ point + row["pose"][:, 3]
    if q[2] <= 0:
        return math.inf
    predicted = np.asarray(row["camera"].img_from_cam(q))
    return float(np.linalg.norm(predicted - row["pixel"]))


def solve_marker(rows: list[dict]) -> tuple[np.ndarray, dict]:
    if len(rows) < 3:
        raise ValueError("RULER_NEEDS_AT_LEAST_THREE_VIEWS")
    candidates = []
    for a, b in itertools.combinations(rows, 2):
        angle = math.degrees(math.acos(float(np.clip(np.dot(a["ray"], b["ray"]), -1, 1))))
        if angle < 8:
            continue
        try:
            point = point_from_rays([a, b])
        except ValueError:
            continue
        errors = np.asarray([pixel_error(point, row) for row in rows])
        inliers = errors < 4.0
        if inliers.sum() >= 3:
            candidates.append((int(inliers.sum()), -float(np.median(errors[inliers])), point, inliers))
    if not candidates:
        raise ValueError("RULER_TRIANGULATION_NO_CONSENSUS")
    _, _, _, inliers = max(candidates, key=lambda item: item[:2])
    point = point_from_rays([row for row, selected in zip(rows, inliers) if selected])
    errors = np.asarray([pixel_error(point, row) for row in rows])
    inliers = errors < 4.0
    if inliers.sum() < 3:
        raise ValueError("RULER_TRIANGULATION_NO_CONSENSUS")
    angles = [math.degrees(math.acos(float(np.clip(np.dot(a["ray"], b["ray"]), -1, 1))))
              for a, b in itertools.combinations([row for row, selected in zip(rows, inliers) if selected], 2)]
    if max(angles) < 12 or np.median(errors[inliers]) > 3.0:
        raise ValueError("RULER_TRIANGULATION_WEAK_GEOMETRY")
    return point, {"observations": len(rows), "inliers": int(inliers.sum()),
                   "medianReprojectionPx": round(float(np.median(errors[inliers])), 3),
                   "maximumBaselineAngleDeg": round(max(angles), 2),
                   "inlierImages": [row["name"] for row, selected in zip(rows, inliers) if selected]}


def calibrate(model_dir: Path, observations_path: Path, source_video: Path, known_length_mm: float = 200.0) -> dict:
    if not 20 <= known_length_mm <= 2000:
        raise ValueError("INVALID_RULER_LENGTH")
    observations = json.loads(observations_path.read_text(encoding="utf-8"))["images"]
    if len({row["name"] for row in observations}) != len(observations):
        raise ValueError("DUPLICATE_RULER_IMAGE")
    model = pycolmap.Reconstruction(str(model_dir))
    images = {image.name: image for image in model.images.values() if image.has_pose}
    marker_rows = {"A": [], "B": []}
    for entry in observations:
        name = entry["name"]
        if name not in images:
            raise ValueError(f"RULER_IMAGE_NOT_REGISTERED:{name}")
        image = images[name]
        camera = model.cameras[image.camera_id]
        pose = np.asarray(image.cam_from_world().matrix())
        center = -pose[:, :3].T @ pose[:, 3]
        for marker in ("A", "B"):
            pixel = np.asarray(entry[marker], float)
            if pixel.shape != (2,) or not np.isfinite(pixel).all() or not (0 <= pixel[0] < camera.width and 0 <= pixel[1] < camera.height):
                raise ValueError(f"RULER_PIXEL_OUT_OF_BOUNDS:{name}:{marker}")
            normalized = np.asarray(camera.cam_from_img(pixel), float)
            ray = pose[:, :3].T @ np.array([normalized[0], normalized[1], 1.0])
            ray /= np.linalg.norm(ray)
            marker_rows[marker].append({"name": name, "pixel": pixel, "camera": camera,
                                        "pose": pose, "center": center, "ray": ray})
    point_a, quality_a = solve_marker(marker_rows["A"])
    point_b, quality_b = solve_marker(marker_rows["B"])
    common = set(quality_a["inlierImages"]) & set(quality_b["inlierImages"])
    if len(common) < 3:
        raise ValueError("RULER_TOO_FEW_COMMON_INLIERS")
    distance = float(np.linalg.norm(point_a - point_b))
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("INVALID_RULER_3D_DISTANCE")
    return {"status": "RULER_SCALED_EXPLORATORY_GEOMETRY", "knownTargetLengthMm": known_length_mm,
            "modelDirectory": str(model_dir.resolve()),
            "modelFilesSha256": {name: sha(model_dir / name) for name in ("cameras.bin", "images.bin", "points3D.bin")
            if (model_dir / name).is_file()},
            "observationFile": str(observations_path.resolve()), "observationSha256": sha(observations_path),
            "sourceVideoSha256": sha(source_video), "targetAColmap": point_a.tolist(), "targetBColmap": point_b.tolist(),
            "reconstructedDistanceColmap": distance, "mmPerColmapUnit": known_length_mm / distance,
            "quality": {"A": quality_a, "B": quality_b, "commonImages": len(common)},
            "surfaceFitVerified": False, "physicalFitVerified": False,
            "warning": "The same video establishes candidate global scale, not local surface accuracy or wearable clearance."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--source-video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--known-mm", type=float, default=200.0)
    args = parser.parse_args()
    result = calibrate(args.model_dir, args.observations, args.source_video, args.known_mm)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "mmPerColmapUnit": result["mmPerColmapUnit"],
                      "quality": result["quality"]}, ensure_ascii=False))
