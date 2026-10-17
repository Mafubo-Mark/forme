"""Audit provenance, ruler scale evidence, and angular sampling of test4 cloud."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from plyfile import PlyData


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def audit(project: Path, submission_id: str) -> dict:
    task = project / "forme-backend" / "data" / "cover_tasks" / submission_id
    model_manifest = json.loads((project / "forme-backend" / "data" / "model_jobs" /
                                 "2eda9bc9-4669-4771-8b88-b80f7c588bee" / "manifest.json").read_text())
    raw = project / "forme-backend" / "data" / "model_jobs" / "2eda9bc9-4669-4771-8b88-b80f7c588bee" / "dense" / "fused.ply"
    prior = project / "work-buddy-handoff" / "models" / "fused-raw-reconstruction.ply"
    subject = project / "analysis" / "isolated-prosthesis.ply"
    video = project / "IMG_3761.MOV"
    hashes = {name: digest(path) for name, path in (("video", video), ("rawCloud", raw),
                                                    ("priorRawCloud", prior), ("subjectCrop", subject))}
    provenance = (hashes["video"] == model_manifest["sourceSha256"] and
                  hashes["rawCloud"] == model_manifest["cloudSha256"] == hashes["priorRawCloud"])
    scale = json.loads((project / "analysis" / "scale-calibration.json").read_text())
    scale_check = json.loads((project / "analysis" / "scale-calibration-original-check.json").read_text())
    scale_spread_percent = (
        abs(scale["mm_per_colmap_unit"] - scale_check["mm_per_colmap_unit"])
        / ((scale["mm_per_colmap_unit"] + scale_check["mm_per_colmap_unit"]) / 2) * 100
    )

    config = json.loads((project / "pointcloud-axis-corrected" / "sections.json").read_text())
    record = PlyData.read(str(subject))["vertex"]
    xyz = np.stack([record[name] for name in ("x", "y", "z")], axis=1).astype(float)
    frame = np.asarray([config["x_in_input_coordinates"], config["front_in_input_coordinates"],
                        config["axis_in_input_coordinates"]]).T
    origin = np.asarray(config["origin_in_input_coordinates"])
    local = (xyz - origin) @ frame * config["input_to_mm_scale"]
    local[:, 2] -= config["trim_low_input_coordinate"] * config["input_to_mm_scale"] + config["cover_start_mm"]
    stations = config["stations"]
    z_controls = np.asarray([s["height_mm"] for s in stations])
    x_controls = np.asarray([s["center_x_mm"] for s in stations])
    y_controls = np.asarray([s["center_y_mm"] for s in stations])
    coverage = []
    for z in np.arange(20, 336, 10):
        band = local[np.abs(local[:, 2] - z) <= 4.0, :2]
        center = np.asarray([np.interp(z, z_controls, x_controls), np.interp(z, z_controls, y_controls)])
        azimuth = np.mod(np.arctan2(band[:, 1] - center[1], band[:, 0] - center[0]), 2 * np.pi)
        counts, _ = np.histogram(azimuth, bins=24, range=(0, 2 * np.pi))
        coverage.append({"axialCoordinateMm": int(z), "pointsIn8MmBand": int(len(band)),
                         "angularBinsWith15PointsOf24": int(np.count_nonzero(counts >= 15))})
    return {
        "status": "PROVENANCE_AND_RULER_CHECKED_LOCAL_SURFACE_NOT_VALIDATED",
        "submissionId": submission_id,
        "videoSha256": hashes["video"],
        "rawCloudSha256": hashes["rawCloud"],
        "subjectCropSha256": hashes["subjectCrop"],
        "provenanceVerified": provenance,
        "artifactOrigin": model_manifest["artifactOrigin"],
        "currentRunGeneratedCloud": False,
        "rawPointCount": int(len(PlyData.read(str(raw))["vertex"])),
        "subjectCropPointCount": int(len(local)),
        "finiteSubjectCoordinates": bool(np.isfinite(local).all()),
        "subjectCropIsVerifiedSegmentation": False,
        "ruler": {
            "nominalTargetLengthMm": scale["measured_ab_mm"],
            "primaryMmPerColmapUnit": scale["mm_per_colmap_unit"],
            "alternateMmPerColmapUnit": scale_check["mm_per_colmap_unit"],
            "sameVideoReconstructionSpreadPercent": round(scale_spread_percent, 4),
            "primaryCommonImages": scale["quality"]["common_images"],
            "medianReprojectionPx": {"targetA": scale["quality"]["A"]["median_reprojection_px"],
                                     "targetB": scale["quality"]["B"]["median_reprojection_px"]},
            "interpretation": "The bar establishes candidate global scale. Reprojection and same-video repeatability do not bound local surface error or verify printed target length.",
        },
        "sampling": {
            "criterion": "At least 15 points in each 15-degree azimuth bin of an 8 mm axial band; occupancy does not prove continuous or accurate surface.",
            "sections": coverage,
            "fullyOccupiedSections": [row["axialCoordinateMm"] for row in coverage if row["angularBinsWith15PointsOf24"] == 24],
            "sparseLowerSections": [row["axialCoordinateMm"] for row in coverage if row["axialCoordinateMm"] < 90 and row["angularBinsWith15PointsOf24"] < 23],
            "sparseUpperSections": [row["axialCoordinateMm"] for row in coverage if row["axialCoordinateMm"] >= 290 and row["angularBinsWith15PointsOf24"] < 23],
        },
        "photoOverlay": str(project / "analysis" / "isolated-photo-overlay.jpg"),
        "surfaceFitVerified": False,
        "suitableFor": ["ruler-scaled visualization", "rough outer silhouette study"],
        "notSuitableFor": ["wearable cavity clearance", "bolt/fastener dimensions", "manufacturing approval"],
        "nextStep": "Use image/point-cloud silhouette checks at matched sections; keep unobserved lower and upper regions explicit. No physical fit verification is possible without an object or test fitting.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--submission-id", required=True)
    args = parser.parse_args()
    result = audit(args.project, args.submission_id)
    output = args.project / "forme-backend" / "data" / "cover_tasks" / args.submission_id / "pointcloud_qa.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "provenanceVerified": result["provenanceVerified"],
                      "fullyOccupiedSections": len(result["sampling"]["fullyOccupiedSections"]),
                      "sections": len(result["sampling"]["sections"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
