"""Estimate the shaft axis from existing section centers using Theil-Sen line fits."""

import json
from pathlib import Path

import numpy as np
from scipy.stats import theilslopes


here = Path(__file__).resolve().parent
old = json.loads((here.parent / "pointcloud-direct-cover-baseline" / "sections.json").read_text())
stations = old["stations"]
z = np.array([s["height_mm"] for s in stations])
cx = np.array([s["center_x_mm"] for s in stations])
cy = np.array([s["center_y_mm"] for s in stations])

# Restrict line fitting to the long central shaft, excluding both end flares.
mask = (z >= 70) & (z <= 225)
if mask.sum() < 6:
    raise ValueError("Too few middle-shaft stations to estimate an axis")
sx = float(theilslopes(cx[mask], z[mask]).slope)
sy = float(theilslopes(cy[mask], z[mask]).slope)
x = np.array(old["x_in_input_coordinates"])
y = np.array(old["front_in_input_coordinates"])
axis = np.array(old["axis_in_input_coordinates"])
corrected = axis + sx * x + sy * y
corrected /= np.linalg.norm(corrected)
angle = float(np.degrees(np.arccos(np.clip(axis @ corrected, -1, 1))))

base_config = json.loads((here.parent / "pointcloud-direct-cover-baseline" / "config.json").read_text())
base_config["axis"] = corrected.tolist()
base_config["max_centerline_tilt_deg"] = 2.0
base_config["design_note"] = (
    "Axis-corrected geometry demo. Main-shaft centerline estimated from existing "
    "cross-section centers with Theil-Sen regression over 70-225 mm. Physical fit unverified."
)
(here / "config.json").write_text(json.dumps(base_config, indent=2) + "\n")
review = {
    "method": "Theil-Sen regression of central-shaft section centers",
    "fitting_range_mm": [70, 225],
    "fitting_station_count": int(mask.sum()),
    "old_axis_in_colmap_coordinates": axis.tolist(),
    "centerline_slope_x_mm_per_mm": sx,
    "centerline_slope_y_mm_per_mm": sy,
    "corrected_axis_in_colmap_coordinates": corrected.tolist(),
    "axis_correction_deg": angle,
}
(here / "axis_review.json").write_text(json.dumps(review, indent=2) + "\n")
print(json.dumps(review, indent=2))
