"""Sample scan points and check whether the FreeCAD shell solid occupies them."""

import json
import sys
from pathlib import Path


here = Path(__file__).resolve().parent
sections = json.loads((here / "sections.json").read_text())
sample_path = here / "scan_sample_local_mm.json"

if sys.argv[1] == "prepare":
    import numpy as np
    from plyfile import PlyData

    points = PlyData.read(sections["source"])["vertex"].data
    xyz = np.column_stack([points[k] for k in ("x", "y", "z")]).astype(float)
    origin = np.array(sections["origin_in_input_coordinates"])
    frame = np.array([
        sections["x_in_input_coordinates"],
        sections["front_in_input_coordinates"],
        sections["axis_in_input_coordinates"],
    ]).T
    scale = sections["input_to_mm_scale"]
    local = (xyz - origin) @ frame * scale
    local[:, 2] -= sections["trim_low_input_coordinate"] * scale + sections["cover_start_mm"]
    local = local[(local[:, 2] >= 0) & (local[:, 2] <= sections["cover_end_mm"] - sections["cover_start_mm"])]
    rng = np.random.default_rng(20260929)
    indices = rng.choice(len(local), min(500, len(local)), replace=False)
    sample_path.write_text(json.dumps(local[indices].round(5).tolist()))
    print(f"Prepared {len(indices)} of {len(local)} cropped scan points")
elif sys.argv[1] == "check":
    import FreeCAD as App

    doc = App.openDocument(str(here / "fitted_c_cover.FCStd"))
    shape = doc.getObject("Fitted_C_cover").Shape
    points = json.loads(sample_path.read_text())
    collisions = []
    for i, xyz in enumerate(points):
        if shape.isInside(App.Vector(*xyz), 0.01, True):
            collisions.append({"sample_index": i, "xyz_mm": xyz})
    report = {
        "sampled_scan_points": len(points),
        "points_inside_shell_material": len(collisions),
        "collision_examples": collisions[:20],
        "interpretation": "Sample-only CAD intersection check; source cloud has known surface gaps and cannot prove physical fit.",
    }
    (here / "scan_intersection_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    App.closeDocument(doc.Name)
else:
    raise SystemExit("use prepare or check")
