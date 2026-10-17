"""Record an operator-reviewed subject crop of the current COLMAP point cloud.

The crop must be prepared and visually reviewed outside this script. Sampling
checks provenance; it cannot prove that every prosthesis surface is accurate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
from plyfile import PlyData
from scipy.spatial import cKDTree


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def xyz(path: Path) -> np.ndarray:
    vertices = PlyData.read(str(path))["vertex"].data
    points = np.column_stack([vertices[key] for key in ("x", "y", "z")]).astype(np.float64)
    if not np.isfinite(points).all():
        raise ValueError("NONFINITE_POINTCLOUD")
    return points


def review(task_root: Path, raw_cloud: Path, subject_crop: Path, source_video: Path, notes: str) -> dict:
    if len(notes.strip()) < 20:
        raise ValueError("OPERATOR_REVIEW_NOTES_REQUIRED")
    ruler_path = task_root / "ruler_calibration.json"
    ruler = json.loads(ruler_path.read_text(encoding="utf-8"))
    video_sha = sha(source_video)
    if ruler.get("sourceVideoSha256") != video_sha:
        raise ValueError("RULER_VIDEO_MISMATCH")
    raw = xyz(raw_cloud)
    crop = xyz(subject_crop)
    if len(crop) < 20000 or len(crop) >= len(raw):
        raise ValueError("SUBJECT_CROP_POINT_COUNT_INVALID")
    sample = crop[np.linspace(0, len(crop) - 1, min(10000, len(crop)), dtype=int)]
    nearest, _ = cKDTree(raw).query(sample, workers=-1)
    tolerance = max(float(np.linalg.norm(np.ptp(raw, axis=0))) * 1e-6, 1e-7)
    if float(np.max(nearest)) > tolerance:
        raise ValueError("CROP_IS_NOT_SUBSET_OF_CURRENT_CLOUD")
    task_root.mkdir(parents=True, exist_ok=True)
    target = task_root / "subject_crop_reviewed.ply"
    if target.exists():
        raise ValueError("SUBJECT_CROP_ALREADY_REVIEWED")
    shutil.copyfile(subject_crop, target)
    report = {"status": "OPERATOR_REVIEWED_SUBJECT_CROP_EXPLORATORY",
              "videoSha256": video_sha, "rawCloudSha256": sha(raw_cloud),
              "subjectCropRelativePath": target.name, "subjectCropSha256": sha(target),
              "rawPointCount": len(raw), "subjectCropPointCount": len(crop),
              "sampledSubsetPoints": len(sample), "maximumSubsetDistanceColmap": float(np.max(nearest)),
              "subjectCropIsVerifiedSegmentation": True, "operatorReviewNotes": notes.strip(),
              "surfaceFitVerified": False, "physicalFitVerified": False,
              "warning": "Operator reviewed crop and sampled provenance; local surface error and wearable clearance remain unknown."}
    (task_root / "pointcloud_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--raw-cloud", type=Path, required=True)
    parser.add_argument("--subject-crop", type=Path, required=True)
    parser.add_argument("--source-video", type=Path, required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--operator-confirmed", action="store_true")
    args = parser.parse_args()
    if not args.operator_confirmed:
        parser.error("OPERATOR_CONFIRMATION_REQUIRED")
    print(json.dumps(review(args.task_root, args.raw_cloud, args.subject_crop,
                            args.source_video, args.notes), ensure_ascii=False))
