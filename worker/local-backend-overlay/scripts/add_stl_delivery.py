"""Add a two-shell STL delivery file to a reviewed front/rear trial package.

The original front and rear STL files remain the preferred slicer inputs. The
combined STL preserves their assembly coordinates and still needs slicer review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

import trimesh


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_stl(package_dir: Path) -> Path:
    report_path = package_dir / "build_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "SLICER_INPUT_CANDIDATE_REVIEW_REQUIRED" or report.get("manufacturingApproved") is not False:
        raise ValueError("REVIEW_STATE_INVALID")
    meshes = []
    for name in ("front", "rear"):
        part = report["parts"][name]
        if part["file"] != f"cover_{name}.stl":
            raise ValueError("UNEXPECTED_PART_FILE")
        path = package_dir / part["file"]
        if not path.is_file() or sha(path) != part["sha256"]:
            raise ValueError(f"{name.upper()}_STL_HASH_MISMATCH")
        mesh = trimesh.load_mesh(path, process=True)
        if len(mesh.faces) != part["triangles"] or not mesh.is_watertight or not mesh.is_winding_consistent:
            raise ValueError(f"{name.upper()}_STL_TOPOLOGY_MISMATCH")
        meshes.append(mesh)
    target = package_dir / "cover_trial_mm.stl"
    if target.is_file() and report.get("combinedStlSha256"):
        if report.get("combinedStl") != target.name or sha(target) != report["combinedStlSha256"]:
            raise ValueError("COMBINED_STL_HASH_MISMATCH")
        return target
    temporary = package_dir / ".cover_trial_mm.stl.building"
    try:
        combined = trimesh.util.concatenate(meshes)
        combined.export(temporary, file_type="stl")
        triangles = sum(len(mesh.faces) for mesh in meshes)
        with temporary.open("rb") as source:
            source.seek(80)
            count = struct.unpack("<I", source.read(4))[0]
        if count != triangles or temporary.stat().st_size != 84 + triangles * 50:
            raise ValueError("COMBINED_STL_INVALID")
        os.replace(temporary, target)
        report.update({"combinedStl": target.name, "combinedStlSha256": sha(target),
                       "combinedTriangles": triangles, "combinedShells": 2,
                       "combinedStlPlacementVerified": False})
        report_temp = report_path.with_suffix(".json.building")
        report_temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(report_temp, report_path)
        return target
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    print(ensure_stl(parser.parse_args().package_dir))
