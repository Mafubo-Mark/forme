"""Package a reviewed two-part trial as a millimeter 3MF slicer input.

Requires trimesh. This is a digital trial package, never a physical fit approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

import trimesh
from add_stl_delivery import ensure_stl


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pack(trial_dir: Path, task_dir: Path) -> Path:
    review_path = task_dir / "candidate_review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    trial_path = Path(review["trialReport"])
    source_analysis_path = Path(review["sourceAnalysis"])
    policy_path = Path(__file__).resolve().parents[2] / "work-buddy-handoff" / "COVER_GENERATION_POLICY.json"
    if sha(policy_path) != review["policySha256"]:
        raise ValueError("GENERATION_POLICY_CHANGED")
    if sha(source_analysis_path) != review["sourceAnalysisSha256"] or json.loads(source_analysis_path.read_text(encoding="utf-8")).get("directPublicGeometryTransfer") is not False:
        raise ValueError("SOURCE_ANALYSIS_INVALID")
    if trial_path.resolve() != (trial_dir / "trial_report.json").resolve() or sha(trial_path) != review["trialReportSha256"]:
        raise ValueError("TRIAL_REPORT_HASH_MISMATCH")
    trial = json.loads(trial_path.read_text(encoding="utf-8"))
    if trial.get("status") != "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED" or review.get("manufacturingApproved") is not False:
        raise ValueError("REVIEW_STATE_INVALID")
    if review.get("candidateId") is None or not all(part in trial["meshes"] for part in ("front", "rear")):
        raise ValueError("TWO_PART_TRIAL_REQUIRED")
    target_dir = task_dir / "candidate_print_trial" / review["candidateId"]
    output = target_dir.with_name(target_dir.name + ".building")
    if target_dir.exists() or output.exists():
        raise ValueError("CANDIDATE_PACKAGE_ALREADY_EXISTS")
    output.mkdir(parents=True)
    parts = {}
    meshes = {}
    try:
        for name in ("front", "rear"):
            item = trial["meshes"][name]
            source = (trial_dir / item["path"]).resolve()
            if not source.is_relative_to(trial_dir.resolve()) or sha(source) != item["sha256"]:
                raise ValueError(f"{name.upper()}_MESH_HASH_MISMATCH")
            target = output / f"cover_{name}.stl"
            shutil.copyfile(source, target)
            mesh = trimesh.load_mesh(target, process=True)
            if not mesh.is_watertight or not mesh.is_winding_consistent or len(mesh.split(only_watertight=False)) != 1:
                raise ValueError(f"{name.upper()}_MESH_TOPOLOGY_FAILED")
            meshes[name] = mesh
            parts[name] = {"file": target.name, "sha256": sha(target), "triangles": len(mesh.faces),
                           "watertight": True, "singleComponent": True, "consistentWinding": True,
                           "boundsMm": mesh.bounds.tolist()}
        z_min = min(mesh.bounds[0, 2] for mesh in meshes.values())
        z_max = max(mesh.bounds[1, 2] for mesh in meshes.values())
        package = output / "cover_trial_mm.3mf"
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
            archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
            with archive.open("3D/3dmodel.model", "w", force_zip64=True) as stream:
                def put(value: str) -> None:
                    stream.write(value.encode("utf-8"))
                put('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="zh-CN" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>\n')
                for object_id, name in enumerate(("front", "rear"), 1):
                    mesh = meshes[name]
                    put(f'<object id="{object_id}" type="model" name={quoteattr(name)}><mesh><vertices>\n')
                    for x, y, z in mesh.vertices:
                        put(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>\n')
                    put('</vertices><triangles>\n')
                    for a, b, c in mesh.faces:
                        put(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>\n')
                    put('</triangles></mesh></object>\n')
                put('</resources><build>\n')
                for object_id in (1, 2):
                    put(f'<item objectid="{object_id}" transform="1 0 0 0 1 0 0 0 1 0 0 {-z_min:.6f}"/>\n')
                put('</build></model>')
        report = {"schemaVersion": 1, "status": "SLICER_INPUT_CANDIDATE_REVIEW_REQUIRED",
                  "candidateId": review["candidateId"], "trialReportSha256": sha(trial_path),
                  "package3mf": package.name, "packageSha256": sha(package), "units": "millimeter",
                  "requiredBuildHeightMm": round(float(z_max - z_min), 3), "parts": parts,
                  "slicerVerified": False, "physicalFitVerified": False, "manufacturingApproved": False,
                  "blockers": review["blockers"]}
        (output / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ensure_stl(output)
        os.replace(output, target_dir)
        return target_dir / "build_report.json"
    except Exception:
        shutil.rmtree(output)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_dir", type=Path)
    parser.add_argument("task_dir", type=Path)
    args = parser.parse_args()
    print(pack(args.trial_dir, args.task_dir))
