"""Build a visual-only template 01 GLB from the ruler-scaled COLMAP envelope.

This deliberately does not produce an STL or claim cavity clearance. It is a
review model while reference segmentation and template registration are open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import trimesh
from scipy.ndimage import gaussian_filter1d

PROJECT = Path(__file__).resolve().parents[2]
SUBMISSION = "fa5c0a40-fd4a-474f-80cf-3da92d7af3a8"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source_sections(vertices: np.ndarray, levels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center = np.empty((len(levels), 2), float)
    extents = np.empty((len(levels), 2), float)
    for i, z in enumerate(levels):
        band = vertices[np.abs(vertices[:, 2] - z) <= 3.0, :2]
        if len(band) < 400:
            raise ValueError(f"Template section at z={z} mm has too few vertices")
        lo, hi = np.quantile(band, [.01, .99], axis=0)
        center[i] = (lo + hi) / 2
        extents[i] = hi - lo
    return gaussian_filter1d(center, 1.0, axis=0), gaussian_filter1d(extents, 1.0, axis=0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-id", default=SUBMISSION)
    args = parser.parse_args()
    task = PROJECT / "forme-backend" / "data" / "cover_tasks" / args.submission_id
    assessment = json.loads((task / "ruler_only_assessment.json").read_text())
    if assessment["status"] != "RULER_SCALED_EXPLORATORY_GEOMETRY":
        raise ValueError("No ruler scaled candidate exists")
    qa_path = task / "pointcloud_qa.json"
    qa = json.loads(qa_path.read_text()) if qa_path.is_file() else None
    template = PROJECT / "work-buddy-handoff" / "templates" / "01"
    catalog = json.loads((PROJECT / "work-buddy-handoff" / "templates" / "catalog.json").read_text())
    source = next(x for x in catalog["templates"] if x["id"] == "01")
    names = ("front.stl", "rear.stl")
    for name in names:
        if sha256(template / name) != source["meshes"][name]["sha256"]:
            raise ValueError(f"Template source hash changed: {name}")
    original = [trimesh.load(template / name, force="mesh") for name in names]
    if any(not isinstance(mesh, trimesh.Trimesh) for mesh in original):
        raise ValueError("Template part missing triangle geometry")

    # The axial coordinate and section widths come from the same video ruler.
    reference = json.loads((PROJECT / "pointcloud-axis-corrected" / "sections.json").read_text())
    if abs(float(reference["input_to_mm_scale"]) - assessment["calibration"]["primaryMmPerColmapUnit"]) > 1e-5:
        raise ValueError("Reference envelope uses a different scale")
    stations = reference["stations"]
    target_z = np.asarray([s["height_mm"] for s in stations], float)
    target_center = gaussian_filter1d(np.asarray([[s["center_x_mm"], s["center_y_mm"]]
                                                  for s in stations], float), 1.0, axis=0)
    # Existing scan envelope uses 2 mm noise margin and 5 mm design clearance.
    # Add its nominal 3 mm wall to make an exterior guide, not a proven cavity.
    wall = float(reference["shell_wall_mm"])
    target_outer = gaussian_filter1d(np.asarray([[s["inner_width_mm"] + 2 * wall,
                                                  s["inner_depth_mm"] + 2 * wall]
                                                 for s in stations], float), 1.0, axis=0)
    z_offset = 20.0
    levels = np.arange(5.0, 311.0, 5.0)
    vertices = np.vstack([m.vertices for m in original])
    source_center, source_outer = source_sections(vertices, levels)
    target_levels = levels + z_offset
    desired_center = np.column_stack([np.interp(target_levels, target_z, target_center[:, i])
                                      for i in range(2)])
    desired_outer = np.column_stack([np.interp(target_levels, target_z, target_outer[:, i])
                                     for i in range(2)])
    requested_scale_xy = gaussian_filter1d(desired_outer / source_outer, 1.0, axis=0)
    if not np.all(np.isfinite(requested_scale_xy)) or np.any(requested_scale_xy < .6):
        raise ValueError("Visual mapping exceeds review limits")
    # Limit motif distortion. Any remaining envelope shortfall is surfaced in
    # the report, never hidden or described as a fit.
    scale_xy = np.clip(requested_scale_xy, .6, 1.7)
    target_shortfall = np.maximum(0.0, desired_outer - source_outer * scale_xy)

    transformed = []
    max_move = 0.0
    for mesh in original:
        copy = mesh.copy()
        v = np.asarray(copy.vertices)
        cx = np.interp(v[:, 2], levels, source_center[:, 0])
        cy = np.interp(v[:, 2], levels, source_center[:, 1])
        tx = np.interp(v[:, 2], levels, desired_center[:, 0])
        ty = np.interp(v[:, 2], levels, desired_center[:, 1])
        sx = np.interp(v[:, 2], levels, scale_xy[:, 0])
        sy = np.interp(v[:, 2], levels, scale_xy[:, 1])
        out = np.column_stack((tx + (v[:, 0] - cx) * sx,
                               ty + (v[:, 1] - cy) * sy,
                               v[:, 2] + z_offset))
        max_move = max(max_move, float(np.linalg.norm(out[:, :2] - v[:, :2], axis=1).max()))
        copy.vertices = out
        copy.fix_normals()
        transformed.append(copy)

    out_dir = task / "ruler_only_template01_concept"
    out_dir.mkdir(parents=True, exist_ok=True)
    colors = ((51, 156, 154, 255), (38, 123, 126, 255))
    scene = trimesh.Scene()
    for mesh, name, color in zip(transformed, ("cloud_front_visual", "cloud_rear_visual"), colors):
        gltf_mesh = mesh.copy()
        # glTF uses Y up. Store (x, z, -y) so Blender/web viewers show the
        # logical ruler-reference Z axis upright after import.
        gltf_mesh.vertices = np.column_stack((mesh.vertices[:, 0], mesh.vertices[:, 2], -mesh.vertices[:, 1]))
        gltf_mesh.visual.vertex_colors = color
        scene.add_geometry(gltf_mesh, geom_name=name)
    glb = out_dir / "template01_ruler_visual.glb"
    glb.write_bytes(scene.export(file_type="glb"))
    report = {
        "status": "VISUAL_CONCEPT_REVIEW_ONLY",
        "submissionId": args.submission_id,
        "templateId": "01",
        "templateName": "祥云",
        "sourceTemplateSha256": source["source_sha256"],
        "sourcePartSha256": {name: sha256(template / name) for name in names},
        "calibration": str(task / "ruler_only_assessment.json"),
        "pointcloudQa": str(qa_path) if qa else None,
        "pointcloudSurfaceFitVerified": qa["surfaceFitVerified"] if qa else False,
        "referenceEnvelope": str(PROJECT / "pointcloud-axis-corrected" / "sections.json"),
        "output": str(glb),
        "outputSha256": sha256(glb),
        "coordinateFrame": "ruler-scaled exploratory reference axial frame, logical Z up, units mm; GLB stored with glTF Y up",
        "heightMapping": {"sourceRangeMm": [0, 315.25], "candidateRangeMm": [20, 335.25]},
        "xyScaleRange": {"x": [float(scale_xy[:, 0].min()), float(scale_xy[:, 0].max())],
                         "y": [float(scale_xy[:, 1].min()), float(scale_xy[:, 1].max())]},
        "clippedScaleControlFraction": float(np.mean(requested_scale_xy > 1.7)),
        "maxExteriorEnvelopeShortfallMm": float(target_shortfall.max()),
        "maxPlanarVertexMoveMm": max_move,
        "parts": [{"name": name, "triangles": len(mesh.faces), "watertight": bool(mesh.is_watertight),
                   "boundsMm": mesh.bounds.tolist()} for name, mesh in zip(names, transformed)],
        "registration": {"verified": False, "frontDirectionVerified": False, "boltPositionVerified": False},
        "fitVerified": False,
        "manufacturingApproved": False,
        "limitations": [
            "The scan envelope is incomplete/noisy and includes inferred clearance; the deformation is an exterior visual guide, not an inner cavity solution.",
            "The source template seam, fastener and interior were not functionally registered to the prosthesis.",
            "The visible side opening is inherited from the source template; it is not a measured bolt cutout.",
            "Only front and rear shells are shown; the rotating tabs were excluded pending fastener registration.",
            "The GLB is for review and is not a print/fit STL.",
        ],
    }
    (out_dir / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"glb": str(glb), "report": str(out_dir / "build_report.json"),
                      "triangles": sum(len(m.faces) for m in transformed),
                      "xyScaleRange": report["xyScaleRange"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
