"""Local WorkBuddy handoff for a frontend submission.

The handoff is an intake package, never an assertion that a cover fits.
"""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

from .store import Store, now

PROJECT = Path(__file__).resolve().parents[3]
CATALOG = PROJECT / "work-buddy-handoff" / "templates" / "catalog.json"
POLICY = PROJECT / "work-buddy-handoff" / "COVER_GENERATION_POLICY.json"


def generation_policy() -> dict:
    raw = POLICY.read_bytes()
    policy = json.loads(raw)
    return {
        "id": policy["policyId"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "path": str(POLICY),
        "upperOpeningIntent": policy["upperOpeningIntent"],
        "releaseRule": policy["releaseRule"],
    }


def candidate_review(folder: Path, policy: dict) -> dict | None:
    path = folder / "candidate_review.json"
    if not path.is_file():
        return None
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
        if review.get("schemaVersion") != 1 or not isinstance(review.get("blockers"), list):
            return {"status": "INVALID_REVIEW", "blockers": ["CANDIDATE_REVIEW_INVALID"]}
        if not isinstance(review.get("candidateId"), str) or not re.fullmatch(r"[a-z0-9_-]{1,40}", review["candidateId"]):
            return {"status": "INVALID_REVIEW", "blockers": ["CANDIDATE_REVIEW_INVALID"]}
        if any(not isinstance(code, str) for code in review["blockers"]):
            return {"status": "INVALID_REVIEW", "blockers": ["CANDIDATE_REVIEW_INVALID"]}
        if review.get("policySha256") != policy["sha256"]:
            return {"status": "STALE_REVIEW", "blockers": ["CANDIDATE_REVIEW_POLICY_CHANGED"]}
        return {
            "status": review.get("status", "CONCEPT_CANDIDATE"),
            "candidateId": review.get("candidateId"),
            "summary": review.get("summary"),
            "maxVertexMoveMm": review.get("maxVertexMoveMm"),
            "upperRimZUnchanged": review.get("upperRimZUnchanged"),
            "blockers": review["blockers"],
            "reportPath": str(path),
            "manufacturingApproved": False,
        }
    except (OSError, ValueError, TypeError):
        return {"status": "INVALID_REVIEW", "blockers": ["CANDIDATE_REVIEW_INVALID"]}


def _sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def registration_current(folder: Path, cloud: Path | None, video_sha: str) -> bool:
    approval_path = folder / "registration_approval.json"
    if not approval_path.is_file() or not cloud or not cloud.is_file():
        return False
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        qa = json.loads((folder / "pointcloud_qa.json").read_text(encoding="utf-8"))
        expected = {"cloudSha256": qa.get("rawCloudSha256"),
                    "rulerReportSha256": _sha(folder / "ruler_calibration.json"),
                    "pointcloudQaSha256": _sha(folder / "pointcloud_qa.json")}
        if approval.get("status") != "OPERATOR_APPROVED_CONCEPT_REGISTRATION" or approval.get("videoSha256") != video_sha:
            return False
        if any(approval.get(key) != sha for key, sha in expected.items()):
            return False
        if len(approval.get("overlaysSha256", {})) < 3:
            return False
        for name, sha in approval["overlaysSha256"].items():
            path = (folder / name).resolve()
            if not path.is_relative_to(folder.resolve()) or _sha(path) != sha:
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def task_status(store: Store, data_dir: Path, submission_id: str) -> dict:
    submission = store.get_submission(submission_id)
    if submission is None:
        raise KeyError("SUBMISSION_NOT_FOUND")
    model = store.model_job_for_submission(submission_id)
    views = store.get_view_review(submission_id)
    blockers = []
    if submission["upload"]["status"] != "accepted":
        blockers.append("CAPTURE_REVIEW_REQUIRED")
    if not views or views["status"] != "reviewed":
        blockers.append("VIEW_SELECTION_REQUIRED")
    folder = data_dir / "cover_tasks" / submission_id
    ruler = folder / "ruler_calibration.json"
    qa = folder / "pointcloud_qa.json"
    approval = folder / "registration_approval.json"
    if not ruler.is_file():
        blockers.append("RULER_CALIBRATION_REQUIRED")
        blockers.append("VERIFIED_MM_REFERENCE_REQUIRED")
    reviewed_crop = False
    if qa.is_file():
        try:
            reviewed_crop = json.loads(qa.read_text(encoding="utf-8")).get("subjectCropIsVerifiedSegmentation") is True
        except (OSError, ValueError):
            pass
    if not reviewed_crop:
        blockers.append("SUBJECT_SEGMENTATION_NOT_REVIEWED")
    cloud = data_dir / "model_jobs" / model["id"] / "dense" / "fused.ply" if model else None
    approved = registration_current(folder, cloud, submission["upload"]["sha256"])
    if not approved:
        blockers.append("TEMPLATE_REGISTRATION_REQUIRED")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    policy = generation_policy()
    review = candidate_review(folder, policy)
    if review:
        blockers.extend(review["blockers"])
    return {
        "status": ("concept_registration_approved" if ruler.is_file() and reviewed_crop and approved and submission["upload"]["status"] == "accepted" and views and views["status"] == "reviewed"
                   else "awaiting_reference_and_registration") if manifest else "not_prepared",
        "blockers": blockers,
        "manifestPath": str(manifest_path) if manifest else None,
        "templateId": manifest.get("templateId") if manifest else None,
        "modelStage": model["stage"] if model else "not_started",
        "viewStatus": views["status"] if views else "not_started",
        "generationPolicy": policy,
        "candidateReview": review,
        "conceptBuildAllowed": bool(ruler.is_file() and reviewed_crop and approved and submission["upload"]["status"] == "accepted" and views and views["status"] == "reviewed"),
        "registrationApprovalPath": str(approval) if approved else None,
    }


def prepare_task(store: Store, data_dir: Path, submission_id: str, template_id: str) -> dict:
    submission = store.get_submission(submission_id)
    if submission is None:
        raise KeyError("SUBMISSION_NOT_FOUND")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    template = next((item for item in catalog["templates"] if item["id"] == template_id), None)
    if template is None:
        raise ValueError("TEMPLATE_NOT_FOUND")
    upload = submission["upload"]
    model = store.model_job_for_submission(submission_id)
    views = store.get_view_review(submission_id)
    frame_root = data_dir / "submissions" / submission_id / "view_frames"
    selections = (views or {}).get("data", {}).get("selections", {})
    frames = {slot: str(frame_root / filename) for slot, filename in selections.items()
              if (frame_root / filename).is_file()}
    cloud = data_dir / "model_jobs" / model["id"] / "dense" / "fused.ply" if model else None
    hunyuan_record_path = data_dir / "cover_tasks" / submission_id / "hunyuan_inputs" / "hunyuan_job.json"
    hunyuan_record = json.loads(hunyuan_record_path.read_text()) if hunyuan_record_path.is_file() else None
    hunyuan_model = hunyuan_record_path.parent / "hunyuan_result" / "result_00.glb"
    has_hunyuan_candidate = bool(hunyuan_record and hunyuan_record.get("status") == "DONE"
                                 and hunyuan_record.get("sourceVideoSha256") == upload["sha256"]
                                 and hunyuan_model.is_file())
    physical_preflight = data_dir / "cover_tasks" / submission_id / "template_physical_preflight.json"
    ruler_only_assessment = data_dir / "cover_tasks" / submission_id / "ruler_only_assessment.json"
    pointcloud_qa = data_dir / "cover_tasks" / submission_id / "pointcloud_qa.json"
    workbuddy_next_task = data_dir / "cover_tasks" / submission_id / "WORKBUDDY_NEXT_TASK.md"
    measurement_checklist = data_dir / "cover_tasks" / submission_id / "MEASUREMENT_CHECKLIST.md"
    visual_concept = data_dir / "cover_tasks" / submission_id / "ruler_only_template01_concept" / "build_report.json"
    manifest = {
        "schemaVersion": 1,
        "submissionId": submission_id,
        "createdAt": now(),
        "templateId": template_id,
        "templateName": template["name"],
        "templateSourceSha256": template["source_sha256"],
        "templateDirectory": template["directory"],
        "choices": {"color": submission["color"], "material": submission["material"],
                    "inspiration": submission["inspiration"]},
        "inputs": {
            "video": str(data_dir / "uploads" / upload["id"] / "source.video"),
            "videoSha256": upload["sha256"],
            "selectedFrames": frames,
            "colmapCloud": str(cloud) if cloud and cloud.is_file() else None,
            "colmapCloudUnits": "unscaled" if cloud and cloud.is_file() else None,
            "hunyuanCandidate": str(hunyuan_model) if has_hunyuan_candidate else None,
            "hunyuanCandidateUnits": "unknown" if has_hunyuan_candidate else None,
            "hunyuanGeometryVerified": False,
            "inspirationImage": str(data_dir / "submissions" / submission_id / "inspiration.image")
            if submission["inspiration_image_name"] else None,
        },
        "instructions": str(PROJECT / "work-buddy-handoff" / "TEMPLATE_ADAPTATION_TASK.md"),
        "generationPolicy": generation_policy(),
        "upperOpeningIntent": "low opening; expose the receiver's high flange",
        "physicalPreflight": str(physical_preflight) if physical_preflight.is_file() else None,
        "rulerOnlyAssessment": str(ruler_only_assessment) if ruler_only_assessment.is_file() else None,
        "pointcloudQa": str(pointcloud_qa) if pointcloud_qa.is_file() else None,
        "workbuddyNextTask": str(workbuddy_next_task) if workbuddy_next_task.is_file() else None,
        "measurementChecklist": str(measurement_checklist) if measurement_checklist.is_file() else None,
        "visualConceptReport": str(visual_concept) if visual_concept.is_file() else None,
        "status": "AWAITING_VERIFIED_MM_REFERENCE_AND_TEMPLATE_REGISTRATION",
        "conceptBuildAllowed": False,
        "nextAction": "使用已重建的 200 mm 标靶建立候选毫米尺度；在相同高度和方向比对模板内腔与点云，并提出不确定性下的可视化设计候选。",
    }
    folder = data_dir / "cover_tasks" / submission_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "manifest.json"
    temporary = folder / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return task_status(store, data_dir, submission_id)
