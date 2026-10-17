"""Make a diagnostic sleeve from calibrated multi-view silhouettes.

This is an image-supported preview, not a verified fit or manufacturing file.
Unlike the older ellipse loft, every axial slice is constrained by the alpha
masks in the registered COLMAP views. 3DGS remains the visual reference.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pycolmap
import trimesh
from scipy import ndimage as ndi
from skimage.measure import marching_cubes

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
BASE = ROOT / 'gs-experiment'
OUT = BASE / 'cad-v5-silhouette-preview'
OUT.mkdir(parents=True, exist_ok=True)
sec = json.loads((BASE / 'cad-v4/sections.json').read_text())
rec = pycolmap.Reconstruction(str(ROOT / 'reconstruction/dense/sparse'))
step = 2.0
grid = np.arange(-120, 122, step, dtype=np.float32)
heights = np.arange(15, 381, step, dtype=np.float32)
xx, yy = np.meshgrid(grid, grid, indexing='xy')
coords = np.column_stack((np.tile(xx.ravel(), len(heights)),
                          np.tile(yy.ravel(), len(heights)),
                          np.repeat(heights, xx.size)))
scale = sec['input_to_mm_scale']
origin = np.asarray(sec['origin_in_input_coordinates'])
x = np.asarray(sec['x_in_input_coordinates'])
y = np.asarray(sec['front_in_input_coordinates'])
z = np.asarray(sec['axis_in_input_coordinates'])
lo = sec['trim_low_input_coordinate']
start = sec['cover_start_mm']
world = (origin + coords[:, 0:1] / scale * x + coords[:, 1:2] / scale * y +
         ((coords[:, 2:3] + start) / scale + lo) * z)
inside = np.zeros(len(world), np.uint16)
seen = np.zeros(len(world), np.uint16)
for k, idx in enumerate(rec.reg_image_ids(), 1):
    im = rec.images[idx]
    cam = rec.cameras[im.camera_id]
    alpha = cv2.imread(str(BASE / 'dataset-alpha/images' / f'{Path(im.name).stem}.png'),
                       cv2.IMREAD_UNCHANGED)
    if alpha is None or alpha.ndim != 3 or alpha.shape[2] != 4:
        raise RuntimeError(f'Missing alpha mask: {im.name}')
    alpha = cv2.resize(alpha[:, :, 3], (cam.width // 2, cam.height // 2),
                       interpolation=cv2.INTER_AREA)
    pose = np.asarray(im.cam_from_world().matrix())
    p = world @ pose[:, :3].T + pose[:, 3]
    fx, fy, cx, cy = np.asarray(cam.params[:4]) / 2
    with np.errstate(divide='ignore', invalid='ignore'):
        u = np.rint(fx * p[:, 0] / p[:, 2] + cx).astype(np.int32)
        v = np.rint(fy * p[:, 1] / p[:, 2] + cy).astype(np.int32)
    valid = (p[:, 2] > 0) & (u >= 0) & (u < alpha.shape[1]) & (v >= 0) & (v < alpha.shape[0])
    vi = np.flatnonzero(valid)
    seen[vi] += 1
    inside[vi] += alpha[v[vi], u[vi]] >= 127
    if k % 20 == 0:
        print(f'Processed {k}/{len(rec.reg_image_ids())} views', flush=True)

support = ((seen >= 40) & (inside >= np.ceil(seen * .93))).reshape(
    len(heights), len(grid), len(grid))
# Smooth only within a voxel; keep the measured concave rim and reject islands.
support = ndi.gaussian_filter(support.astype(np.float32), (.55, .65, .65)) > .48
labels, number = ndi.label(support)
if number < 1:
    raise RuntimeError('No multi-view silhouette agreement')
sizes = np.bincount(labels.ravel())
sizes[0] = 0
support = labels == np.argmax(sizes)
slice_area = support.sum(axis=(1, 2)) * step * step
print('Supported z range (mm):', heights[np.flatnonzero(slice_area > 100)[[0, -1]]], flush=True)

# Build a continuous signed distance field from the measured cross-sections.
# Only lateral distance is used, so the photographed top opening is not capped.
clearance_mm = 5.0
wall_mm = 3.0
distance = np.full(support.shape, 1000, dtype=np.float32)
for i, section in enumerate(support):
    if slice_area[i] < 300:
        continue
    outside = ndi.distance_transform_edt(~section) * step
    inside_distance = ndi.distance_transform_edt(section) * step
    distance[i] = outside - inside_distance
distance = ndi.gaussian_filter(distance, sigma=(4.0, 2.5, 2.5))
field = np.minimum(distance - clearance_mm,
                   clearance_mm + wall_mm - distance)

# Remove a narrow C opening from the side opposite the measured bolt side.
stations = sec['stations']
station_z = np.array([s['height_mm'] for s in stations])
cx = np.interp(heights, station_z, [s['center_x_mm'] for s in stations])
cy = np.interp(heights, station_z, [s['center_y_mm'] for s in stations])
angle = np.arctan2(yy[None, :, :] - cy[:, None, None],
                   xx[None, :, :] - cx[:, None, None])
radius = np.hypot(xx[None, :, :] - cx[:, None, None],
                  yy[None, :, :] - cy[:, None, None])
opening_distance = (np.abs(angle) - np.deg2rad(14)) * radius
field = np.minimum(field, opening_distance)

# Smooth only the cut transition, then extract a continuous sub-voxel isosurface.
field = ndi.gaussian_filter(field, sigma=(.55, .55, .55))
shell = field > 0
verts, faces, _, _ = marching_cubes(np.pad(field, 1, constant_values=-20), 0,
                                    spacing=(step, step, step))
verts -= step
vertices = np.column_stack((grid[0] + verts[:, 2], grid[0] + verts[:, 1],
                            heights[0] + verts[:, 0]))
mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
components = sorted(mesh.split(only_watertight=False), key=lambda m: abs(m.volume), reverse=True)
mesh = components[0]
mesh.export(OUT / 'silhouette_sleeve_preview.stl')
np.savez_compressed(OUT / 'silhouette_volume.npz', support=support, shell=shell,
                    x_mm=grid, y_mm=grid, z_mm=heights, area_mm2=slice_area)
report = {
    'status': 'GEOMETRY REVIEW ONLY — NOT PRINT APPROVED',
    'method': '87-view silhouette intersection, 93% agreement, 2 mm grid, smoothed signed-distance isosurface',
    'source': 'test4 video alpha masks and COLMAP cameras; 3DGS used as visual reference',
    'calibration_mm_per_colmap_unit': scale,
    'clearance_mm_preview': clearance_mm,
    'wall_mm_preview': wall_mm,
    'opening_angle_deg_preview': 28,
    'connected_components_before_largest_only': len(components),
    'mesh_watertight': bool(mesh.is_watertight),
    'warnings': ['Silhouette intersection does not resolve hidden concavities or precise socket fit.',
                 'The 2 mm source grid and smoothed surface are a visual prototype, not a fabrication tolerance.',
                 'No verified bolt clearance is cut into this preview.',
                 'Top-rim placement requires measurement and manual review.'],
}
(OUT / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print('Wrote', OUT / 'silhouette_sleeve_preview.stl', 'faces', len(mesh.faces),
      'watertight', mesh.is_watertight, flush=True)
