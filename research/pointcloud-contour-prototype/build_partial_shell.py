"""Build a scan-derived *partial* C shell from observed cross sections.

Uses OpenCV raster morphology/contours for the section and clearance offsets,
then Trimesh to join the sections. No surface is inferred above the last
well-observed station or around the unmeasured base fastener.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from plyfile import PlyData
from scipy.ndimage import gaussian_filter, gaussian_filter1d, maximum_filter1d
import trimesh


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "pointcloud-axis-corrected" / "sections.json"
GRID_MM = 0.5
GRID_HALF_MM = 105.0
SLICE_HALF_MM = 4.0
STATIONS_MM = [float(z) for z in np.arange(150, 271, 7.5)] + [275.0]
OPENING_CENTER_DEG = 90.0
OPENING_DEG = 64.0
CLEARANCE_MM = 5.0
WALL_MM = 3.0
ENVELOPE_MM = 2.0
JOIN_MM = 1.5
ANGLE_COUNT = 241


def kernel(radius_mm: float) -> np.ndarray:
    radius_px = round(radius_mm / GRID_MM)
    side = radius_px * 2 + 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))


def largest_contour(mask: np.ndarray) -> np.ndarray:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("No contours found")
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) * GRID_MM**2 < 2500:
        raise ValueError("Observed contour is too small")
    return contour[:, 0, :].astype(float)


def radial_profile(contour: np.ndarray, center: np.ndarray, angles: np.ndarray) -> np.ndarray:
    # Contour vertices from OpenCV are dense, but their polar samples are uneven.
    xy = np.column_stack((contour[:, 0] * GRID_MM - GRID_HALF_MM,
                          GRID_HALF_MM - contour[:, 1] * GRID_MM))
    rel = xy - center
    theta = np.mod(np.arctan2(rel[:, 1], rel[:, 0]), 2 * np.pi)
    radius = np.linalg.norm(rel, axis=1)
    order = np.argsort(theta)
    theta, radius = theta[order], radius[order]
    wrapped_theta = np.r_[theta - 2 * np.pi, theta, theta + 2 * np.pi]
    wrapped_radius = np.tile(radius, 3)
    r = np.interp(np.mod(angles, 2 * np.pi), wrapped_theta, wrapped_radius)
    return gaussian_filter1d(r, 0.65, mode="nearest")


def load_points(config: dict) -> np.ndarray:
    data = PlyData.read(config["source"])["vertex"].data
    xyz = np.column_stack([data[k] for k in ("x", "y", "z")]).astype(float)
    origin = np.asarray(config["origin_in_input_coordinates"])
    frame = np.asarray([config["x_in_input_coordinates"],
                        config["front_in_input_coordinates"],
                        config["axis_in_input_coordinates"]]).T
    local = (xyz - origin) @ frame * config["input_to_mm_scale"]
    local[:, 2] -= (config["trim_low_input_coordinate"] * config["input_to_mm_scale"]
                    + config["cover_start_mm"])
    return local


def section(points: np.ndarray, z: float, center: np.ndarray, angles: np.ndarray,
            min_angular_bins: int = 23) -> tuple[np.ndarray, np.ndarray, dict]:
    band = points[np.abs(points[:, 2] - z) <= SLICE_HALF_MM, :2]
    if len(band) < 1000:
        raise ValueError(f"Too few points at {z} mm: {len(band)}")
    n = round(2 * GRID_HALF_MM / GRID_MM) + 1
    pixels = np.rint((band + np.array([GRID_HALF_MM, -GRID_HALF_MM]))
                      * np.array([1, -1]) / GRID_MM).astype(int)
    valid = ((pixels[:, 0] >= 0) & (pixels[:, 0] < n)
             & (pixels[:, 1] >= 0) & (pixels[:, 1] < n))
    pixels = pixels[valid]
    raster = np.zeros((n, n), np.uint8)
    raster[pixels[:, 1], pixels[:, 0]] = 255
    # Standard raster contour extraction: join small sampling gaps, then fill
    # the observed object's largest connected outer contour.
    joined = cv2.morphologyEx(cv2.dilate(raster, kernel(JOIN_MM)),
                              cv2.MORPH_CLOSE, kernel(4.0))
    observed_contour = largest_contour(joined)
    filled = np.zeros_like(raster)
    cv2.drawContours(filled, [observed_contour.astype(np.int32).reshape(-1, 1, 2)],
                     -1, 255, thickness=cv2.FILLED)
    # The initial join dilation is already part of the 2 mm scan envelope.
    inner_mask = cv2.dilate(filled, kernel(ENVELOPE_MM - JOIN_MM + CLEARANCE_MM))
    outer_mask = cv2.dilate(filled, kernel(ENVELOPE_MM - JOIN_MM + CLEARANCE_MM + WALL_MM))
    observed = radial_profile(observed_contour, center, angles)
    inner = radial_profile(largest_contour(inner_mask), center, angles)
    outer = radial_profile(largest_contour(outer_mask), center, angles)
    if np.any(outer <= inner + 1):
        raise ValueError(f"Offset surfaces crossed at {z} mm")
    observed_full = radial_profile(observed_contour, center, np.linspace(0, 2*np.pi, 96, endpoint=False))
    scan_angle = np.mod(np.arctan2(band[:, 1] - center[1], band[:, 0] - center[0]), 2*np.pi)
    counts, _ = np.histogram(scan_angle, bins=24, range=(0, 2*np.pi))
    if np.count_nonzero(counts >= 15) < min_angular_bins:
        raise ValueError(f"Incomplete angular coverage at {z} mm")
    return inner, outer, {
        "z_mm": z,
        "points_in_8mm_band": len(band),
        "angular_bins_with_15_points_of_24": int(np.count_nonzero(counts >= 15)),
        "observed_radius_min_mm": round(float(observed_full.min()), 2),
        "observed_radius_max_mm": round(float(observed_full.max()), 2),
        "median_inner_minus_observed_radial_mm": round(float(np.median(inner - observed)), 2),
    }


def build_mesh(profiles: list[dict], angles: np.ndarray) -> trimesh.Trimesh:
    count = len(angles)
    vertices = []
    for s in profiles:
        for kind in ("inner", "outer"):
            radii = np.asarray(s[kind])
            vertices.extend(np.column_stack((s["center"][0] + radii*np.cos(angles),
                                             s["center"][1] + radii*np.sin(angles),
                                             np.full(count, s["z_mm"]))))
    vertices = np.asarray(vertices)
    faces = []
    def quad(a, b, c, d):
        faces.extend(((a, b, c), (a, c, d)))
    for j in range(len(profiles) - 1):
        a, b = j*2*count, (j+1)*2*count
        for i in range(count-1):
            quad(a+i, a+i+1, b+i+1, b+i)  # inner
            quad(a+count+i+1, a+count+i, b+count+i, b+count+i+1)  # outer
        quad(a, b, b+count, a+count)  # first side of C opening
        quad(a+count-1, a+2*count-1, b+2*count-1, b+count-1)
    for a, reverse in ((0, True), ((len(profiles)-1)*2*count, False)):
        for i in range(count-1):
            v = (a+i, a+i+1, a+count+i+1, a+count+i)
            quad(*reversed(v) if reverse else v)
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces), process=True)
    trimesh.repair.fix_normals(mesh)
    return mesh


def render_sections(points: np.ndarray, profiles: list[dict], angles: np.ndarray, config: dict) -> None:
    selected = [150, 175, 200, 225, 250, 275]
    im = Image.new("RGB", (1500, len(selected)*410), "white")
    draw = ImageDraw.Draw(im)
    for row, z in enumerate(selected):
        s = min(profiles, key=lambda v: abs(v["z_mm"]-z))
        z = s["z_mm"]
        center = np.asarray(s["center"])
        band = points[np.abs(points[:, 2]-z) <= SLICE_HALF_MM, :2]
        rng = np.random.default_rng(int(z))
        band = band[rng.choice(len(band), min(3000, len(band)), replace=False)]
        px, py, scale = 300, row*410+205, 2.45
        coord = lambda p: (px + p[0]*scale, py - p[1]*scale)
        draw.text((10, row*410+10), f"z={z} mm; observed dots, inner green, outer orange, rejected ellipse blue", fill="black")
        for p in band:
            x, y = coord(p)
            draw.ellipse((x-1, y-1, x+1, y+1), fill="#a0a0a0")
        for key, color in (("inner", "#16844f"), ("outer", "#d66a22")):
            curve = [coord(center + r*np.array([np.cos(t), np.sin(t)]))
                     for r, t in zip(s[key], angles)]
            draw.line(curve, fill=color, width=3)
        old = min(config["stations"], key=lambda v: abs(v["height_mm"]-z))
        ts = np.linspace(0, 2*np.pi, 200)
        old_curve = [coord(np.array([old["center_x_mm"]+old["inner_width_mm"]/2*np.cos(t),
                                     old["center_y_mm"]+old["inner_depth_mm"]/2*np.sin(t)])) for t in ts]
        draw.line(old_curve, fill="#236fc2", width=2)
        draw.line([(750, row*410), (750, (row+1)*410)], fill="#dddddd", width=2)
        draw.text((780, row*410+28), f"measured section: {s['report']['points_in_8mm_band']} points", fill="black")
        draw.text((780, row*410+58), f"angular coverage: {s['report']['angular_bins_with_15_points_of_24']}/24", fill="black")
        draw.text((780, row*410+88), f"inner clearance (radial median): {s['report']['median_inner_minus_observed_radial_mm']} mm", fill="black")
    im.save(ROOT / "section_comparison.png")


def audit_scan_clearance(points: np.ndarray, profiles: list[dict], angles: np.ndarray) -> dict:
    sample = points[(points[:, 2] >= STATIONS_MM[0]) & (points[:, 2] <= STATIONS_MM[-1])]
    if len(sample) > 100000:
        sample = sample[np.random.default_rng(17).choice(len(sample), 100000, replace=False)]
    zs = np.asarray([p["z_mm"] for p in profiles])
    cent = np.asarray([p["center"] for p in profiles])
    inner = np.asarray([p["inner"] for p in profiles])
    idx = np.clip(np.searchsorted(zs, sample[:, 2]) - 1, 0, len(zs)-2)
    blend = (sample[:, 2] - zs[idx]) / (zs[idx+1] - zs[idx])
    center = cent[idx]*(1-blend[:, None]) + cent[idx+1]*blend[:, None]
    xy = sample[:, :2] - center
    theta = np.mod(np.arctan2(xy[:, 1], xy[:, 0]) - angles[0], 2*np.pi) + angles[0]
    included = theta <= angles[-1]
    theta, idx, blend, xy = theta[included], idx[included], blend[included], xy[included]
    angle_idx = np.clip(np.searchsorted(angles, theta)-1, 0, len(angles)-2)
    angle_blend = (theta-angles[angle_idx]) / (angles[angle_idx+1]-angles[angle_idx])
    r0 = inner[idx, angle_idx]*(1-angle_blend) + inner[idx, angle_idx+1]*angle_blend
    r1 = inner[idx+1, angle_idx]*(1-angle_blend) + inner[idx+1, angle_idx+1]*angle_blend
    gap = r0*(1-blend) + r1*blend - np.linalg.norm(xy, axis=1)
    return {"sampled_points_within_shell_angle": len(gap),
            "radial_gap_p01_mm": round(float(np.quantile(gap, .01)), 2),
            "radial_gap_median_mm": round(float(np.median(gap)), 2),
            "radial_gap_min_mm": round(float(gap.min()), 2),
            "points_radially_outside_inner_surface": int(np.count_nonzero(gap < 0)),
            "points_with_less_than_2mm_radial_gap": int(np.count_nonzero(gap < 2))}


def render_mesh(mesh: trimesh.Trimesh) -> None:
    im = Image.new("RGB", (1600, 900), "#f5f7f8")
    draw = ImageDraw.Draw(im)
    vertices = mesh.vertices
    center = vertices.mean(axis=0)
    for panel, position in enumerate(((1.25, 1.75, 0.65), (-1.4, -1.0, 0.65))):
        eye = center + np.asarray(position)*300
        forward = center-eye
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, [0, 0, 1.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        planar = np.column_stack(((vertices-center)@right, (vertices-center)@up))
        lo, hi = planar.min(axis=0), planar.max(axis=0)
        scale = min(700/(hi[0]-lo[0]), 720/(hi[1]-lo[1]))
        px = panel*800+400+(planar[:, 0]-(lo[0]+hi[0])/2)*scale
        py = 460-(planar[:, 1]-(lo[1]+hi[1])/2)*scale
        depths = (vertices[mesh.faces].mean(axis=1)-eye)@forward
        order = np.argsort(depths)[::-1]
        light = np.asarray([.35, -.25, .9])
        light /= np.linalg.norm(light)
        shades = np.clip(.35 + .55*np.abs(mesh.face_normals@light), 0, 1)
        for index in order:
            face = mesh.faces[index]
            intensity = shades[index]
            color = (int(27+58*intensity), int(86+110*intensity), int(104+110*intensity))
            draw.polygon([(float(px[v]), float(py[v])) for v in face], fill=color)
        title = "Opening side" if panel == 0 else "Back side"
        draw.text((panel*800+24, 25), title + f" | z={mesh.bounds[0,2]:.0f}–{mesh.bounds[1,2]:.0f} mm", fill="#172d37")
    im.save(ROOT / "mesh_preview.png")


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    config = json.loads(SOURCE.read_text())
    points = load_points(config)
    begin = np.deg2rad(OPENING_CENTER_DEG + OPENING_DEG/2)
    end = begin + 2*np.pi - np.deg2rad(OPENING_DEG)
    angles = np.linspace(begin, end, ANGLE_COUNT)
    profiles = []
    for z in STATIONS_MM:
        old = min(config["stations"], key=lambda v: abs(v["height_mm"]-z))
        center = np.array([old["center_x_mm"], old["center_y_mm"]])
        inner, outer, report = section(points, z, center, angles)
        profiles.append({"z_mm": z, "center": center.tolist(), "inner": inner.tolist(),
                         "outer": outer.tolist(), "report": report})
    # Mild Gaussian fairing is standard mesh/profile postprocessing. Keep the
    # actual unsmoothed section measurements in each station's report.
    for kind in ("inner", "outer"):
        values = np.asarray([p[kind] for p in profiles])
        values = maximum_filter1d(values, size=3, axis=0, mode="nearest")
        values = gaussian_filter(values, sigma=(1.35, 1.25), mode="nearest")
        for p, row in zip(profiles, values):
            p[kind] = row.tolist()
    mesh = build_mesh(profiles, angles)
    mesh.export(ROOT / "partial_contour_shell.stl")
    mesh.export(ROOT / "partial_contour_shell.ply")
    render_sections(points, profiles, angles, config)
    render_mesh(mesh)
    (ROOT / "profiles.json").write_text(json.dumps({"angles_rad": angles.tolist(),
        "stations": profiles}, indent=2) + "\n")
    report = {"status": "SCAN-DERIVED PARTIAL GEOMETRY PROTOTYPE; NOT FIT-VERIFIED",
              "coverage_z_mm": [min(STATIONS_MM), max(STATIONS_MM)],
              "unmodeled_base_bolt_z_mm_approx": [40, 60],
              "unmodeled_upper_scan_z_mm_approx": [300, 325],
              "clearance_mm_nominal": CLEARANCE_MM,
              "envelope_mm": ENVELOPE_MM, "wall_mm_nominal": WALL_MM,
              "mesh_watertight": bool(mesh.is_watertight),
              "mesh_winding_consistent": bool(mesh.is_winding_consistent),
              "mesh_components": len(mesh.split(only_watertight=False)),
              "mesh_volume_mm3": float(mesh.volume),
              "sampled_scan_clearance": audit_scan_clearance(points, profiles, angles),
              "stations": [p["report"] for p in profiles]}
    (ROOT / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k:v for k,v in report.items() if k != "stations"}, indent=2))


if __name__ == "__main__":
    main()
