#!/usr/bin/env python3
"""Attach the earlier same-capture trial to the cloud demo for transport testing.

This deliberately does not claim that the current COLMAP run fitted the cover.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from forme_backend.cover_automation import generation_policy
from forme_backend.store import Store


PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "forme-backend" / "data"
DEMO = Path(__file__).resolve().parent
SOURCE = DEMO / "candidate_print_trial" / "demo-2026-10-12"
SOURCE_SUBMISSION = "fa5c0a40-fd4a-474f-80cf-3da92d7af3a8"
TARGET_SUBMISSION = "d4ca3886da744c19a2adaa212bcfb9d4"
CANDIDATE_ID = "replay-same-video-v1"
BLOCKER = "REPLAYED_GEOMETRY_NOT_REGENERATED_FROM_CURRENT_POINTCLOUD"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    submission = Store(DATA).get_submission(TARGET_SUBMISSION)
    model = Store(DATA).model_job_for_submission(TARGET_SUBMISSION)
    if not submission or submission["upload"]["status"] != "accepted":
        raise ValueError("DEMO_SUBMISSION_NOT_ACCEPTED")
    if not model or model["stage"] != "scale_review":
        raise ValueError("CURRENT_COLMAP_RUN_NOT_COMPLETE")
    model_dir = DATA / "model_jobs" / model["id"]
    model_manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    if model_manifest["sourceSha256"] != submission["upload"]["sha256"]:
        raise ValueError("CURRENT_COLMAP_VIDEO_MISMATCH")
    task_dir = DATA / "cover_tasks" / TARGET_SUBMISSION
    if not (task_dir / "pointcloud_qa.json").is_file():
        raise ValueError("CURRENT_POINTCLOUD_AUDIT_REQUIRED")
    source_report = json.loads((SOURCE / "build_report.json").read_text(encoding="utf-8"))
    if sha256(SOURCE / "cover_trial_mm.3mf") != source_report["packageSha256"]:
        raise ValueError("SOURCE_PACKAGE_HASH_MISMATCH")
    for part in ("front", "rear"):
        record = source_report["parts"][part]
        if sha256(SOURCE / record["file"]) != record["sha256"]:
            raise ValueError("SOURCE_PART_HASH_MISMATCH")
    output = task_dir / "candidate_print_trial" / CANDIDATE_ID
    if output.exists() or (task_dir / "candidate_review.json").exists():
        raise ValueError("REPLAY_ALREADY_ATTACHED")
    output.mkdir(parents=True)
    try:
        for name in ("cover_trial_mm.3mf", "cover_front.stl", "cover_rear.stl"):
            shutil.copyfile(SOURCE / name, output / name)
        blockers = list(dict.fromkeys([*source_report["blockers"], BLOCKER,
                                        "CURRENT_CLOUD_SUBJECT_SEGMENTATION_NOT_REVIEWED",
                                        "CURRENT_HUNYUAN_MODEL_NOT_USED_IN_REPLAY_GEOMETRY"]))
        report = {**source_report, "candidateId": CANDIDATE_ID, "blockers": blockers,
                  "sourceMode": "HISTORICAL_SAME_CAPTURE_REPLAY_FOR_BRIDGE_VALIDATION",
                  "sourceSubmissionId": SOURCE_SUBMISSION,
                  "currentSubmissionId": TARGET_SUBMISSION,
                  "currentVideoSha256": submission["upload"]["sha256"],
                  "currentColmapCloudSha256": model_manifest["cloudSha256"],
                  "currentColmapCloudUsedToFitThisPackage": False,
                  "currentHunyuanModelUsedToFitThisPackage": False,
                  "customerReleaseApproved": False}
        (output / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        review = {"schemaVersion": 1, "status": "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED",
                  "candidateId": CANDIDATE_ID, "policySha256": generation_policy()["sha256"],
                  "summary": "同一拍摄素材的历史数字试样复用，仅用于验证云端文件回传；当前新点云和混元白模未重新拟合此保护套。",
                  "manufacturingApproved": False, "physicalFitVerified": False,
                  "blockers": blockers, "trialReport": str(DEMO / "trial_report.json"),
                  "sourceAnalysis": str(DEMO / "source_analysis.json")}
        (task_dir / "candidate_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(output)
        raise
    print(json.dumps({"candidateId": CANDIDATE_ID, "packageSha256": sha256(output / "cover_trial_mm.3mf"),
                      "sourceMode": report["sourceMode"], "customerReleaseApproved": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
