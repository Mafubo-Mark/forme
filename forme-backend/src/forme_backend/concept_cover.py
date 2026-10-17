"""Operator gated template morph for a digital trial candidate.

WorkBuddy may propose controls, but it cannot grant itself registration approval.
The approved artifacts are hashed and checked again immediately before building.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from .cover_automation import CATALOG, generation_policy
from .production_flow import digest, write_json


class CoverGateError(ValueError):
    pass


def _artifact(task_root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise CoverGateError("INVALID_EVIDENCE_PATH")
    path = (task_root / relative).resolve()
    if not path.is_relative_to(task_root.resolve()) or not path.is_file():
        raise CoverGateError("EVIDENCE_FILE_MISSING")
    return path


def _prerequisites(task_root: Path, video_sha: str, cloud: Path) -> tuple[dict, dict]:
    ruler_path = task_root / "ruler_calibration.json"
    qa_path = task_root / "pointcloud_qa.json"
    if not ruler_path.is_file():
        raise CoverGateError("RULER_CALIBRATION_REQUIRED")
    if not qa_path.is_file():
        raise CoverGateError("SUBJECT_POINTCLOUD_REVIEW_REQUIRED")
    ruler = json.loads(ruler_path.read_text(encoding="utf-8"))
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    if (ruler.get("status") != "RULER_SCALED_EXPLORATORY_GEOMETRY"
            or ruler.get("knownTargetLengthMm") != 200.0
            or ruler.get("sourceVideoSha256") != video_sha
            or ruler.get("quality", {}).get("commonImages", 0) < 3):
        raise CoverGateError("RULER_EVIDENCE_INVALID")
    model_dir = Path(ruler.get("modelDirectory", ""))
    model_hashes = ruler.get("modelFilesSha256", {})
    if set(model_hashes) != {"cameras.bin", "images.bin", "points3D.bin"}:
        raise CoverGateError("RULER_MODEL_HASH_MISSING")
    for name, expected_sha in model_hashes.items():
        source = model_dir / name
        if name not in ("cameras.bin", "images.bin", "points3D.bin") or not source.is_file() or digest(source) != expected_sha:
            raise CoverGateError("RULER_MODEL_HASH_MISMATCH")
    if not math.isfinite(ruler.get("mmPerColmapUnit", float("nan"))) or ruler["mmPerColmapUnit"] <= 0:
        raise CoverGateError("RULER_SCALE_INVALID")
    if qa.get("videoSha256") != video_sha or qa.get("rawCloudSha256") != digest(cloud):
        raise CoverGateError("POINTCLOUD_PROVENANCE_INVALID")
    if qa.get("subjectCropIsVerifiedSegmentation") is not True:
        raise CoverGateError("SUBJECT_SEGMENTATION_NOT_REVIEWED")
    subject = _artifact(task_root, qa.get("subjectCropRelativePath"))
    if digest(subject) != qa.get("subjectCropSha256"):
        raise CoverGateError("SUBJECT_CROP_HASH_MISMATCH")
    return ruler, qa


def approve_registration(task_root: Path, video_sha: str, cloud: Path, payload: dict) -> dict:
    ruler, qa = _prerequisites(task_root, video_sha, cloud)
    manifest_path = task_root / "manifest.json"
    if not manifest_path.is_file():
        raise CoverGateError("COVER_TASK_NOT_PREPARED")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    template = next((item for item in json.loads(CATALOG.read_text(encoding="utf-8"))["templates"]
                     if item["id"] == manifest.get("templateId")), None)
    if not template or template["source_sha256"] != manifest.get("templateSourceSha256"):
        raise CoverGateError("TEMPLATE_SOURCE_CHANGED")
    transform = payload.get("cloudToTemplateTransform")
    if not isinstance(transform, list) or len(transform) != 4 or any(not isinstance(row, list) or len(row) != 4 for row in transform):
        raise CoverGateError("INVALID_REGISTRATION_TRANSFORM")
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for row in transform for value in row):
        raise CoverGateError("INVALID_REGISTRATION_TRANSFORM")
    if any(abs(transform[3][i] - [0, 0, 0, 1][i]) > 1e-6 for i in range(4)):
        raise CoverGateError("INVALID_REGISTRATION_TRANSFORM")
    scale = ruler["mmPerColmapUnit"]
    columns = [[transform[row][column] for row in range(3)] for column in range(3)]
    norms = [math.sqrt(sum(value * value for value in column)) for column in columns]
    if any(abs(norm / scale - 1) > 0.02 for norm in norms):
        raise CoverGateError("REGISTRATION_SCALE_DISAGREES_WITH_RULER")
    if any(abs(sum(a * b for a, b in zip(columns[i], columns[j]))) > .02 * scale * scale
           for i, j in ((0, 1), (0, 2), (1, 2))):
        raise CoverGateError("REGISTRATION_ROTATION_NOT_ORTHOGONAL")
    cross = [columns[0][1] * columns[1][2] - columns[0][2] * columns[1][1],
             columns[0][2] * columns[1][0] - columns[0][0] * columns[1][2],
             columns[0][0] * columns[1][1] - columns[0][1] * columns[1][0]]
    if sum(a * b for a, b in zip(cross, columns[2])) <= 0:
        raise CoverGateError("REGISTRATION_REFLECTION_NOT_ALLOWED")
    notes = payload.get("notes")
    if not isinstance(notes, str) or len(notes.strip()) < 20:
        raise CoverGateError("REGISTRATION_REVIEW_NOTES_REQUIRED")
    overlay_names = payload.get("overlayPaths")
    if not isinstance(overlay_names, list) or len(set(overlay_names)) < 3:
        raise CoverGateError("THREE_REGISTRATION_OVERLAYS_REQUIRED")
    overlays = {name: digest(_artifact(task_root, name)) for name in overlay_names}
    record = {"schemaVersion": 1, "status": "OPERATOR_APPROVED_CONCEPT_REGISTRATION",
              "scope": "digital_trial_candidate_only", "videoSha256": video_sha,
              "cloudSha256": digest(cloud), "rulerReportSha256": digest(task_root / "ruler_calibration.json"),
              "pointcloudQaSha256": digest(task_root / "pointcloud_qa.json"),
              "subjectCropSha256": qa["subjectCropSha256"],
              "mmPerColmapUnit": ruler["mmPerColmapUnit"],
              "templateId": template["id"], "templateSourceSha256": template["source_sha256"],
              "cloudToTemplateTransform": transform, "overlaysSha256": overlays,
              "notes": notes.strip(), "physicalFitVerified": False}
    write_json(task_root / "registration_approval.json", record)
    return record


def build_candidate(task_root: Path, video_sha: str, cloud: Path, candidate_id: str,
                    proposal: dict, geometry_python: str, fit_script: Path) -> dict:
    if not isinstance(candidate_id, str) or not re.fullmatch(r"[a-z0-9_-]{1,40}", candidate_id):
        raise CoverGateError("INVALID_CANDIDATE_ID")
    _, qa = _prerequisites(task_root, video_sha, cloud)
    approval_path = task_root / "registration_approval.json"
    if not approval_path.is_file():
        raise CoverGateError("REGISTRATION_APPROVAL_REQUIRED")
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if approval.get("status") != "OPERATOR_APPROVED_CONCEPT_REGISTRATION" or approval.get("videoSha256") != video_sha:
        raise CoverGateError("REGISTRATION_APPROVAL_INVALID")
    expected = {"cloudSha256": digest(cloud),
                "rulerReportSha256": digest(task_root / "ruler_calibration.json"),
                "pointcloudQaSha256": digest(task_root / "pointcloud_qa.json")}
    if any(approval.get(key) != value for key, value in expected.items()):
        raise CoverGateError("REGISTRATION_INPUT_CHANGED")
    for name, sha in approval.get("overlaysSha256", {}).items():
        if digest(_artifact(task_root, name)) != sha:
            raise CoverGateError("REGISTRATION_OVERLAY_CHANGED")
    template = next((item for item in json.loads(CATALOG.read_text(encoding="utf-8"))["templates"]
                     if item["id"] == approval.get("templateId")), None)
    if not template or template["source_sha256"] != approval.get("templateSourceSha256"):
        raise CoverGateError("TEMPLATE_SOURCE_CHANGED")
    manifest = json.loads((task_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("templateId") != template["id"] or manifest.get("templateSourceSha256") != template["source_sha256"]:
        raise CoverGateError("COVER_TASK_TEMPLATE_CHANGED")
    controls = proposal.get("controls")
    height = template["shell_height_mm"]
    if not isinstance(controls, list) or len(controls) < 3 or any(not isinstance(row, dict) for row in controls):
        raise CoverGateError("UPPER_RIM_CONTROLS_REQUIRED")
    last_two = controls[-2:]
    if abs(last_two[0].get("z_mm", -1) - (height - 30)) > 1 or last_two[1].get("z_mm", -1) < height:
        raise CoverGateError("UPPER_RIM_CONTROLS_REQUIRED")
    if any(abs(row.get(key, 1)) > 1e-6 for row in last_two for key in ("dx_mm", "dy_mm", "radial_x_mm", "radial_y_mm")):
        raise CoverGateError("UPPER_RIM_MUST_REMAIN_UNCHANGED")
    output = task_root / "concept_candidates" / candidate_id
    temporary = output.with_name(output.name + ".building")
    if output.exists() or temporary.exists():
        raise CoverGateError("CANDIDATE_ALREADY_EXISTS")
    temporary.mkdir(parents=True)
    spec = {"schema_version": 1, "template_id": template["id"],
            "source_sha256": template["source_sha256"],
            "template_axis_xy_mm": proposal.get("template_axis_xy_mm"), "controls": controls,
            "approval": "concept_geometry_only",
            "registration": {"verified": True, "units": "mm", "z_up": True,
                             "rear_positive_y": True, "reference_artifact": str(_artifact(task_root, qa["subjectCropRelativePath"])),
                             "evidence": str(approval_path)}}
    try:
        write_json(temporary / "proposal.json", spec)
        result = subprocess.run([geometry_python, str(fit_script), str(temporary / "proposal.json"), str(temporary)],
                                text=True, capture_output=True, timeout=1800, check=False)
        if result.returncode:
            raise CoverGateError("CONCEPT_BUILD_FAILED:" + result.stderr[-300:])
        fit = json.loads((temporary / "fit_report.json").read_text(encoding="utf-8"))
        names = list(fit["mesh_metrics"])
        if len(names) != 2:
            raise CoverGateError("TWO_PART_COVER_REQUIRED")
        trial = {"status": "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED", "candidateId": candidate_id,
                 "meshes": {side: {"path": name, "sha256": fit["mesh_metrics"][name]["sha256"]}
                            for side, name in zip(("front", "rear"), names)},
                 "physicalFitVerified": False}
        source = {"directPublicGeometryTransfer": False, "source": "registered_local_template",
                  "templateId": template["id"], "registrationApprovalSha256": digest(approval_path)}
        write_json(temporary / "trial_report.json", trial)
        write_json(temporary / "source_analysis.json", source)
        trial_sha, source_sha = digest(temporary / "trial_report.json"), digest(temporary / "source_analysis.json")
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    policy = generation_policy()
    review = {"schemaVersion": 1, "candidateId": candidate_id,
              "status": "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED", "summary": "已按操作员确认的标尺和配准生成受限模板形变；仅供数字试样审查。",
              "policyId": policy["id"], "policySha256": policy["sha256"],
              "trialReport": str(output / "trial_report.json"), "trialReportSha256": trial_sha,
              "sourceAnalysis": str(output / "source_analysis.json"), "sourceAnalysisSha256": source_sha,
              "maxVertexMoveMm": max(row["max_vertex_move_mm"] for row in fit["mesh_metrics"].values()),
              "upperRimZUnchanged": True,
              "blockers": ["LOCAL_THICKNESS_AND_SELF_INTERSECTION_REVIEW_REQUIRED", "SLICER_PROFILE_CHECK_REQUIRED",
                           "FASTENER_AND_PHYSICAL_FIT_UNVERIFIED"], "manufacturingApproved": False}
    write_json(task_root / "candidate_review.json", review)
    return {"status": review["status"], "candidateId": candidate_id,
            "fitReport": str(output / "fit_report.json"), "physicalFitVerified": False}
