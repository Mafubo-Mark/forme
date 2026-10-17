"""Draw raw scan sections, convex hulls, and the rejected elliptical profiles."""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from plyfile import PlyData
from scipy.spatial import ConvexHull


here = Path(__file__).resolve().parent
d = json.loads((here / "sections.json").read_text())
v = PlyData.read(d["source"])["vertex"].data
xyz = np.column_stack([v[k] for k in ("x", "y", "z")]).astype(float)
rgb = np.column_stack([v[k] for k in ("red", "green", "blue")]).astype(int)
origin = np.array(d["origin_in_input_coordinates"])
frame = np.array([d["x_in_input_coordinates"], d["front_in_input_coordinates"], d["axis_in_input_coordinates"]]).T
local = (xyz - origin) @ frame * d["input_to_mm_scale"]
local[:, 2] -= d["trim_low_input_coordinate"] * d["input_to_mm_scale"] + d["cover_start_mm"]

zs = [40, 70, 150, 200, 250, 275, 300, 325]
w, h = 1200, 2400
im = Image.new("RGB", (w, h), "white")
draw = ImageDraw.Draw(im)
for i, z in enumerate(zs):
    box_x = (i % 2) * 600
    box_y = (i // 2) * 600
    points = local[np.abs(local[:, 2] - z) < 5, :2]
    indices = np.flatnonzero(np.abs(local[:, 2] - z) < 5)
    brightness = rgb[indices].mean(axis=1)
    if len(points) > 3000:
        rng = np.random.default_rng(i)
        sel = rng.choice(len(points), 3000, replace=False)
        drawn = points[sel]
        colors = brightness[sel]
    else:
        drawn, colors = points, brightness
    cx, cy = box_x + 300, box_y + 310
    scale = 3.1
    cvt = lambda p: (cx + p[0] * scale, cy - p[1] * scale)
    draw.rectangle((box_x + 1, box_y + 1, box_x + 599, box_y + 599), outline="#dddddd", width=2)
    draw.text((box_x + 15, box_y + 15), f"z={z} mm   points={len(points)}", fill="black")
    for p, bright in zip(drawn, colors):
        x, y = cvt(p)
        color = "#777777" if bright < 110 else "#c6c6c6"
        draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=color)
    if len(points) >= 3:
        hull = ConvexHull(points)
        poly = [cvt(p) for p in points[hull.vertices]]
        draw.line(poly + poly[:1], fill="#da4b35", width=3)
    nearest = min(d["stations"], key=lambda s: abs(s["height_mm"] - z))
    ex, ey = nearest["center_x_mm"], nearest["center_y_mm"]
    rx, ry = nearest["inner_width_mm"] / 2, nearest["inner_depth_mm"] / 2
    theta = np.linspace(0, 2 * np.pi, 180)
    ellipse = [cvt((ex + rx * np.cos(t), ey + ry * np.sin(t))) for t in theta]
    draw.line(ellipse + ellipse[:1], fill="#2585d0", width=2)
    draw.text((box_x + 15, box_y + 565), "red: raw convex hull    blue: old ellipse", fill="black")
im.save(here / "cross_section_diagnostic.png")
