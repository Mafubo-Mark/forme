"""Package the reviewed V2 cover as a slicer-importable prototype.

Run with a Python environment that provides trimesh. This deliberately preserves
the reviewed geometry: experimental reinforcement/remesh variants are excluded.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

import trimesh


TASK_ID = "fa5c0a40-fd4a-474f-80cf-3da92d7af3a8"
ROOT = Path(__file__).resolve().parents[1] / "data" / "cover_tasks" / TASK_ID
OUTPUT = ROOT / "print_prototype_v1"
SOURCES = {
    "front": ROOT / "workbuddy_hybrid_v2" / "cover_front_review_candidate.stl",
    "rear": ROOT / "workbuddy_hybrid_v2" / "cover_rear_review_candidate.stl",
}
THICKNESS = OUTPUT / "wall_thickness_sample.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_model(z_offset: float) -> None:
    package = OUTPUT / "xiangyun_v2_print_trial_mm.3mf"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("[Content_Types].xml", '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>''')
        archive.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>''')
        with archive.open("3D/3dmodel.model", "w", force_zip64=True) as out:
            def put(value: str) -> None:
                out.write(value.encode("utf-8"))

            put('<?xml version="1.0" encoding="UTF-8"?>\n')
            put('<model unit="millimeter" xml:lang="zh-CN" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n')
            put('<metadata name="Title">Forme 祥云 V2 打印试样</metadata><resources>\n')
            for object_id, (name, path) in enumerate(SOURCES.items(), 1):
                mesh = trimesh.load_mesh(path, process=True)
                put(f'<object id="{object_id}" type="model" name={quoteattr(name)}><mesh><vertices>\n')
                for x, y, z in mesh.vertices:
                    put(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>\n')
                put('</vertices><triangles>\n')
                for a, b, c in mesh.faces:
                    put(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>\n')
                put('</triangles></mesh></object>\n')
            put('</resources><build>\n')
            for object_id in (1, 2):
                put(f'<item objectid="{object_id}" transform="1 0 0 0 1 0 0 0 1 0 0 {z_offset:.6f}"/>\n')
            put('</build></model>')


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    thickness = json.loads(THICKNESS.read_text())
    parts = {}
    bounds = []
    for name, source in SOURCES.items():
        target = OUTPUT / f"cover_{name}_print_test.stl"
        if not target.is_file() or sha256(target) != sha256(source):
            target.write_bytes(source.read_bytes())
        mesh = trimesh.load_mesh(target, process=True)
        if not mesh.is_watertight or not mesh.is_winding_consistent or len(mesh.split(only_watertight=False)) != 1:
            raise RuntimeError(f"Mesh checks failed: {target}")
        bounds.append(mesh.bounds)
        sample = next(p for p in thickness["parts"] if name in Path(p["path"]).name)
        parts[name] = {
            "file": target.name,
            "sha256": sha256(target),
            "triangles": len(mesh.faces),
            "watertight": True,
            "singleComponent": True,
            "consistentWinding": True,
            "boundsMm": mesh.bounds.tolist(),
            "sizeMm": mesh.extents.tolist(),
            "volumeCm3": round(mesh.volume / 1000, 3),
            "sampledWallMm": sample["thicknessMm"],
            "sampledBelow1_2Mm": sample["sampledBelow1_2Mm"],
        }
    z_min = min(b[0][2] for b in bounds)
    write_model(-z_min)
    package = OUTPUT / "xiangyun_v2_print_trial_mm.3mf"
    report = {
        "status": "SLICER_INPUT_TRIAL_NOT_FIT_VERIFIED",
        "taskId": TASK_ID,
        "source": "workbuddy_hybrid_v2; geometry preserved",
        "package3mf": package.name,
        "packageSha256": sha256(package),
        "units": "millimeter",
        "packageZOffsetMm": -z_min,
        "requiredBuildHeightMm": max(b[1][2] for b in bounds) - z_min,
        "parts": parts,
        "knownIssues": [
            "Side opening edges near Z 75-105 mm have sampled sub-1.2 mm sharp regions; slicer preview and local test print required.",
            "Fastener/rotating tabs have not been adapted or verified for this V2 body.",
            "Inner cavity, physical fit, holding force and wearer safety are unverified; ruler-derived geometry only.",
            "No printer-specific slicing or G-code has been generated.",
        ],
    }
    (OUTPUT / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
