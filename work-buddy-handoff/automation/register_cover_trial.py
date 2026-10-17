"""Register a geometry trial for operator review; this never grants build approval."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "work-buddy-handoff" / "COVER_GENERATION_POLICY.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def register(trial_dir: Path, task_dir: Path, candidate_id: str) -> Path:
    report_path = trial_dir / "trial_report.json"
    source_path = trial_dir / "source_analysis.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if report.get("status") != "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED":
        raise ValueError("trial must remain a concept candidate")
    if source.get("directPublicGeometryTransfer") is not False:
        raise ValueError("public geometry transfer needs a separate license decision")
    for part in ("front", "rear"):
        mesh = report["meshes"][part]
        path = (trial_dir / mesh["path"]).resolve()
        if not path.is_relative_to(trial_dir.resolve()) or digest(path) != mesh["sha256"]:
            raise ValueError(f"{part} mesh hash or path mismatch")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    review = {
        "schemaVersion": 1,
        "candidateId": candidate_id,
        "status": "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED",
        "summary": "可信点云段小幅平滑修形；上口低开口意图保留。仍不能据此判定可生产或佩戴。",
        "policyId": policy["policyId"],
        "policySha256": digest(POLICY),
        "trialReport": str(report_path.resolve()),
        "trialReportSha256": digest(report_path),
        "sourceAnalysis": str(source_path.resolve()),
        "sourceAnalysisSha256": digest(source_path),
        "meshSha256": {part: report["meshes"][part]["sha256"] for part in ("front", "rear")},
        "maxVertexMoveMm": report["maxVertexMoveMm"],
        "upperRimZUnchanged": report["upperRimZUnchanged"],
        "sameSourcePointcloudMetricOnly": True,
        "independentPriorSubjects": 1,
        "directPublicGeometryTransfer": False,
        "blockers": [
            "UPPER_EDGE_CLEARANCE_UNVERIFIED",
            "SIDE_OPENING_THIN_EDGE",
            "LOCAL_THICKNESS_AND_SELF_INTERSECTION_REVIEW_REQUIRED",
            "SLICER_PROFILE_CHECK_REQUIRED",
            "FASTENER_AND_PHYSICAL_FIT_UNVERIFIED"
        ],
        "manufacturingApproved": False
    }
    task_dir.mkdir(parents=True, exist_ok=True)
    target = task_dir / "candidate_review.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_dir", type=Path)
    parser.add_argument("task_dir", type=Path)
    parser.add_argument("candidate_id")
    args = parser.parse_args()
    print(register(args.trial_dir, args.task_dir, args.candidate_id))
