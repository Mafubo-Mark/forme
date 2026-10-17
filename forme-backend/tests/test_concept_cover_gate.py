from __future__ import annotations

import json
from pathlib import Path

import pytest

from forme_backend.concept_cover import CoverGateError, approve_registration, build_candidate
from forme_backend.cover_automation import CATALOG
from forme_backend.production_flow import digest, write_json


def test_cover_build_requires_reviewed_crop_and_registration(tmp_path: Path) -> None:
    task = tmp_path / "task"
    task.mkdir()
    cloud = tmp_path / "fused.ply"
    cloud.write_bytes(b"raw pointcloud")
    crop = task / "subject_crop_reviewed.ply"
    crop.write_bytes(b"reviewed crop")
    overlay_names = []
    for index in range(3):
        name = f"overlay_{index}.png"
        (task / name).write_bytes(f"overlay {index}".encode())
        overlay_names.append(name)
    template = next(item for item in json.loads(CATALOG.read_text())["templates"] if item["id"] == "04")
    write_json(task / "manifest.json", {"templateId": "04", "templateSourceSha256": template["source_sha256"]})
    model_dir = tmp_path / "sparse"
    model_dir.mkdir()
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        (model_dir / name).write_bytes(name.encode())
    write_json(task / "ruler_calibration.json", {
        "status": "RULER_SCALED_EXPLORATORY_GEOMETRY", "knownTargetLengthMm": 200.0,
        "sourceVideoSha256": "video", "mmPerColmapUnit": 141.2,
        "modelDirectory": str(model_dir),
        "modelFilesSha256": {name: digest(model_dir / name) for name in ("cameras.bin", "images.bin", "points3D.bin")},
        "quality": {"commonImages": 5}})
    qa = {"videoSha256": "video", "rawCloudSha256": digest(cloud),
          "subjectCropRelativePath": crop.name, "subjectCropSha256": digest(crop),
          "subjectCropIsVerifiedSegmentation": False}
    write_json(task / "pointcloud_qa.json", qa)
    payload = {"cloudToTemplateTransform": [[141.2, 0, 0, 0], [0, 141.2, 0, 0],
                                              [0, 0, 141.2, 0], [0, 0, 0, 1]],
               "overlayPaths": overlay_names, "notes": "Operator inspected segmentation and three registration overlays."}
    with pytest.raises(CoverGateError, match="SUBJECT_SEGMENTATION_NOT_REVIEWED"):
        approve_registration(task, "video", cloud, payload)
    qa["subjectCropIsVerifiedSegmentation"] = True
    write_json(task / "pointcloud_qa.json", qa)
    wrong_scale = {**payload, "cloudToTemplateTransform": [[100, 0, 0, 0], [0, 100, 0, 0],
                                                              [0, 0, 100, 0], [0, 0, 0, 1]]}
    with pytest.raises(CoverGateError, match="REGISTRATION_SCALE_DISAGREES_WITH_RULER"):
        approve_registration(task, "video", cloud, wrong_scale)
    approved = approve_registration(task, "video", cloud, payload)
    assert approved["physicalFitVerified"] is False
    (task / overlay_names[0]).write_bytes(b"changed")
    height = template["shell_height_mm"]
    proposal = {"template_axis_xy_mm": [0, 0], "controls": [
        {"z_mm": 0, "dx_mm": 0, "dy_mm": 0, "radial_x_mm": 0, "radial_y_mm": 0},
        {"z_mm": height - 30, "dx_mm": 0, "dy_mm": 0, "radial_x_mm": 0, "radial_y_mm": 0},
        {"z_mm": height, "dx_mm": 0, "dy_mm": 0, "radial_x_mm": 0, "radial_y_mm": 0}]}
    with pytest.raises(CoverGateError, match="REGISTRATION_OVERLAY_CHANGED"):
        build_candidate(task, "video", cloud, "candidate-v1", proposal, "python", Path("fit_template.py"))
