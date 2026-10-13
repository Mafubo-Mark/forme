"""Per-submission production evidence and the reviewed Hunyuan input handoff."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .cover_automation import task_status
from .store import Store
from .view_review import SLOTS


class FlowError(ValueError):
    pass


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def prepare_hunyuan_input(store: Store, data_dir: Path, submission_id: str) -> dict:
    submission = store.get_submission(submission_id)
    if submission is None:
        raise KeyError("SUBMISSION_NOT_FOUND")
    if submission["upload"]["status"] != "accepted":
        raise FlowError("CAPTURE_REVIEW_REQUIRED")
    review = store.get_view_review(submission_id)
    if not review or review["status"] != "reviewed":
        raise FlowError("SIX_VIEWS_REVIEW_REQUIRED")
    selections = review["data"].get("selections", {})
    if set(selections) != set(SLOTS):
        raise FlowError("SIX_VIEWS_REVIEW_REQUIRED")
    frame_records = {item["name"]: item for item in review["data"].get("frames", [])}
    frame_root = data_dir / "submissions" / submission_id / "view_frames"
    source_video = data_dir / "uploads" / submission["upload_id"] / "source.video"
    if not source_video.is_file() or digest(source_video) != submission["upload"]["sha256"]:
        raise FlowError("SOURCE_VIDEO_HASH_MISMATCH")
    selected = []
    for slot in SLOTS:
        name = selections[slot]
        record = frame_records.get(name)
        source = frame_root / name
        if not record or not source.is_file() or digest(source) != record.get("sha256"):
            raise FlowError("SELECTED_FRAME_HASH_MISMATCH")
        if source.stat().st_size > 6_000_000 or not source.read_bytes().startswith(b"\xff\xd8\xff"):
            raise FlowError("SELECTED_FRAME_INVALID")
        selected.append((slot, name, source, record["sha256"]))
    folder = data_dir / "cover_tasks" / submission_id / "hunyuan_inputs"
    manifest_path = folder / "manifest.json"
    job_path = folder / "hunyuan_job.json"
    if job_path.exists():
        raise FlowError("HUNYUAN_JOB_ALREADY_SUBMITTED")
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous_selections = {item["slot"]: (item["sourceFrame"], item["sha256"])
                               for item in previous.get("images", []) if item["slot"] in SLOTS}
        current_selections = {slot: (name, sha) for slot, name, _, sha in selected}
        if previous.get("sourceVideoSha256") != submission["upload"]["sha256"] or previous_selections != current_selections:
            raise FlowError("HUNYUAN_PACKAGE_ALREADY_EXISTS_WITH_DIFFERENT_INPUTS")
        for slot, _, _, sha in selected:
            if not (folder / f"{slot}.jpg").is_file() or digest(folder / f"{slot}.jpg") != sha:
                raise FlowError("HUNYUAN_PACKAGE_HASH_MISMATCH")
        return {"status": "prepared_not_submitted", "manifestPath": str(manifest_path),
                "views": list(SLOTS), "sourceVideoSha256": submission["upload"]["sha256"]}
    folder.mkdir(parents=True, exist_ok=True)
    images = []
    for slot, name, source, sha in selected:
        target = folder / f"{slot}.jpg"
        temporary = target.with_suffix(".jpg.tmp")
        temporary.write_bytes(source.read_bytes())
        os.replace(temporary, target)
        images.append({"slot": slot, "selectedBy": "operator", "sourceFrame": name,
                       "path": str(target.resolve()), "sha256": sha})
    manifest = {"submissionId": submission_id, "sourceVideoSha256": submission["upload"]["sha256"],
                "status": "prepared_not_submitted", "images": images,
                "note": "Front/left/right/back are provider inputs; top and bolt are review-only views."}
    write_json(manifest_path, manifest)
    return {"status": manifest["status"], "manifestPath": str(manifest_path),
            "views": list(SLOTS), "sourceVideoSha256": manifest["sourceVideoSha256"]}


def workflow_snapshot(store: Store, data_dir: Path, submission_id: str) -> dict:
    submission = store.get_submission(submission_id)
    if submission is None:
        raise KeyError("SUBMISSION_NOT_FOUND")
    upload = submission["upload"]
    views = store.get_view_review(submission_id)
    model = store.model_job_for_submission(submission_id)
    task_root = data_dir / "cover_tasks" / submission_id
    package = task_root / "hunyuan_inputs" / "manifest.json"
    package_record = json.loads(package.read_text(encoding="utf-8")) if package.is_file() else None
    package_ready = bool(package_record and package_record.get("sourceVideoSha256") == upload["sha256"]
                         and package_record.get("status") == "prepared_not_submitted")
    hunyuan_path = task_root / "hunyuan_inputs" / "hunyuan_job.json"
    attempt_path = task_root / "hunyuan_inputs" / "hunyuan_submission_attempt.json"
    hunyuan = json.loads(hunyuan_path.read_text(encoding="utf-8")) if hunyuan_path.is_file() else None
    attempt = json.loads(attempt_path.read_text(encoding="utf-8")) if attempt_path.is_file() else None
    cover = task_status(store, data_dir, submission_id)
    candidate = cover["candidateReview"]
    candidate_id = candidate.get("candidateId") if candidate else None
    package_root = task_root / "candidate_print_trial" / candidate_id if candidate_id and re.fullmatch(r"[a-z0-9_-]{1,40}", candidate_id) else None
    package_report_path = package_root / "build_report.json" if package_root else None
    package_report = json.loads(package_report_path.read_text(encoding="utf-8")) if package_report_path and package_report_path.is_file() else None
    trial_package_ready = bool(package_report and package_report.get("status") == "SLICER_INPUT_CANDIDATE_REVIEW_REQUIRED"
                         and package_report.get("candidateId") == candidate_id
                         and package_report.get("package3mf") == "cover_trial_mm.3mf"
                         and (package_root / "cover_trial_mm.3mf").is_file()
                         and package_report.get("combinedStl") == "cover_trial_mm.stl"
                         and package_report.get("combinedStlSha256")
                         and (package_root / "cover_trial_mm.stl").is_file())
    ruler_path = task_root / "ruler_calibration.json"
    ruler = json.loads(ruler_path.read_text(encoding="utf-8")) if ruler_path.is_file() else None
    if ruler and ruler.get("sourceVideoSha256") != upload["sha256"]:
        ruler = None
    pointcloud_qa = (task_root / "pointcloud_qa.json").is_file()
    ruler_assessed = (task_root / "ruler_only_assessment.json").is_file()
    stages = [
        {"id": "capture", "label": "视频质检与拍摄复核", "state": "done" if upload["status"] == "accepted" else "waiting", "detail": upload["status"]},
        {"id": "views", "label": "六视角人工确认", "state": "done" if views and views["status"] == "reviewed" else "waiting", "detail": views["status"] if views else "not_started"},
        {"id": "colmap", "label": "COLMAP 点云", "state": "done" if model and model["stage"] == "scale_review" else "waiting", "detail": model["stage"] if model else "not_started"},
        {"id": "hunyuan_input", "label": "混元输入打包", "state": "done" if package_ready else "waiting", "detail": "prepared" if package_ready else "not_prepared"},
        {"id": "hunyuan_result", "label": "混元白模归档", "state": "done" if hunyuan and hunyuan.get("status") == "DONE" and (task_root / "hunyuan_inputs" / "hunyuan_result" / "result_00.glb").is_file() else "waiting", "detail": hunyuan.get("status") if hunyuan else "submission_outcome_uncertain" if attempt else "not_submitted"},
        {"id": "ruler_qa", "label": "标尺与点云复核", "state": "done" if cover["registrationApprovalPath"] else "review" if ruler or ruler_assessed or pointcloud_qa else "waiting", "detail": "exploratory_only" if ruler or ruler_assessed else "not_started"},
        {"id": "cover_task", "label": "模板与 WorkBuddy 交接", "state": "done" if cover["manifestPath"] else "waiting", "detail": cover["status"]},
        {"id": "registration", "label": "点云与模板配准复核", "state": "done" if cover["registrationApprovalPath"] else "waiting", "detail": "concept_only_approved" if cover["registrationApprovalPath"] else "operator_review_required"},
        {"id": "candidate_review", "label": "候选网格与质量审核", "state": "review" if candidate and candidate["status"] == "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED" else "waiting", "detail": candidate["status"] if candidate else "not_started"},
        {"id": "print_trial", "label": "STL 数字试样与切片复核", "state": "review" if trial_package_ready else "waiting", "detail": "slicer_input_ready_not_sliced" if trial_package_ready else "not_packaged"},
    ]
    next_stage = next((stage["id"] for stage in stages if stage["state"] != "done"), "print_trial")
    return {"submissionId": submission_id, "stages": stages, "nextStage": next_stage,
            "hunyuanSubmissionAttempt": attempt.get("status") if attempt and not hunyuan else None,
            "rulerCalibration": None if not ruler else {"mmPerColmapUnit": ruler["mmPerColmapUnit"],
                                                       "commonImages": ruler["quality"]["commonImages"],
                                                       "surfaceFitVerified": False},
            "trialCandidate": None if not trial_package_ready else {
                "candidateId": candidate_id, "packageUrl": f"/api/internal/submissions/{submission_id}/print-candidate/package",
                "stlUrl": f"/api/internal/submissions/{submission_id}/print-candidate/stl/combined",
                "stlSha256": package_report["combinedStlSha256"],
                "frontStlUrl": f"/api/internal/submissions/{submission_id}/print-candidate/stl/front",
                "rearStlUrl": f"/api/internal/submissions/{submission_id}/print-candidate/stl/rear",
                "requiredBuildHeightMm": package_report["requiredBuildHeightMm"],
                "slicerVerified": False, "physicalFitVerified": False},
            "conceptBuildAllowed": cover["conceptBuildAllowed"], "manufacturingApproved": False,
            "blockers": cover["blockers"]}
