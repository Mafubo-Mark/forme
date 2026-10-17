"""Record a conservative provenance audit for a newly reconstructed submission.

The raw COLMAP cloud contains background points. This audit deliberately does
not certify a prosthesis crop, local accuracy, template registration, or fit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from plyfile import PlyData


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(data_dir: Path, submission_id: str, model_job_id: str) -> dict:
    model_dir = data_dir / "model_jobs" / model_job_id
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    cloud = model_dir / "dense" / "fused.ply"
    ruler = data_dir / "cover_tasks" / submission_id / "ruler_calibration.json"
    report = json.loads(ruler.read_text(encoding="utf-8"))
    from forme_backend.store import Store
    submission = Store(data_dir).get_submission(submission_id)
    if submission is None:
        raise ValueError("SUBMISSION_NOT_FOUND")
    video = data_dir / "uploads" / submission["upload_id"] / "source.video"
    video_sha, cloud_sha = sha256(video), sha256(cloud)
    provenance = (video_sha == manifest["sourceSha256"] == report["sourceVideoSha256"]
                  == submission["upload"]["sha256"] and cloud_sha == manifest["cloudSha256"])
    vertices = PlyData.read(str(cloud))["vertex"]
    xyz = np.stack([vertices[axis] for axis in ("x", "y", "z")], axis=1).astype(np.float64)
    finite = bool(np.isfinite(xyz).all())
    if not finite or len(xyz) != manifest["pointCount"]:
        raise ValueError("POINT_CLOUD_DATA_INVALID")
    return {
        "status": "NEW_COLMAP_RAW_CLOUD_PROVENANCE_CHECKED_SURFACE_NOT_VALIDATED",
        "submissionId": submission_id,
        "modelJobId": model_job_id,
        "videoSha256": video_sha,
        "rawCloudSha256": cloud_sha,
        "provenanceVerified": provenance,
        "currentRunGeneratedCloud": True,
        "rawPointCount": int(len(xyz)),
        "finiteRawCoordinates": finite,
        "rawBoundsColmapUnits": [xyz.min(axis=0).tolist(), xyz.max(axis=0).tolist()],
        "subjectCropIsVerifiedSegmentation": False,
        "surfaceFitVerified": False,
        "physicalFitVerified": False,
        "ruler": {
            "knownTargetLengthMm": report["knownTargetLengthMm"],
            "mmPerColmapUnit": report["mmPerColmapUnit"],
            "commonImages": report["quality"]["commonImages"],
            "interpretation": "Global scale candidate from the same video; not a bound on local surface error.",
        },
        "sampling": {"sections": [], "fullyOccupiedSections": [],
                     "sparseLowerSections": [], "sparseUpperSections": [],
                     "criterion": "No subject-only angular coverage is reported before segmentation review."},
        "suitableFor": ["raw reconstruction provenance", "global scale candidate", "subject segmentation review"],
        "notSuitableFor": ["wearable cavity clearance", "bolt dimensions", "manufacturing approval"],
        "nextStep": "Review the prosthesis crop, image overlays, and template registration before producing a new fitted cover candidate.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--model-job-id", required=True)
    args = parser.parse_args()
    result = audit(args.data_dir, args.submission_id, args.model_job_id)
    output = args.data_dir / "cover_tasks" / args.submission_id / "pointcloud_qa.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "provenanceVerified": result["provenanceVerified"],
                      "pointCount": result["rawPointCount"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
