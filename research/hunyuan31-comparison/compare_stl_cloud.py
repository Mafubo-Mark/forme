"""Align Hunyuan STL to test4 COLMAP data and report observed-region residuals.

The STL carries no physical units. The 200 mm photogrammetry bar gives units to
the target cloud; the mesh receives its similarity scale during registration.
Fits deliberately use the white shaft only, so receiver error remains visible.
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from plyfile import PlyData
from scipy.spatial import cKDTree
from scipy.spatial import ConvexHull, distance
import trimesh

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
OUT = ROOT / 'hunyuan31-comparison'
rng = np.random.default_rng(20260929)
cfg = json.loads((ROOT / 'analysis/isolation-config.json').read_text())
mm_per_unit = json.loads((ROOT / 'analysis/scale-calibration.json').read_text())['mm_per_colmap_unit']
origin = np.asarray(cfg['origin_colmap'], float)
axis = np.asarray(cfg['axis_colmap'], float)
axis /= np.linalg.norm(axis)
xaxis = np.cross(axis, [1.0, 0.0, 0.0]); xaxis /= np.linalg.norm(xaxis)
yaxis = np.cross(axis, xaxis)
basis = np.stack([xaxis, yaxis, -axis], axis=1)

ply = PlyData.read(str(ROOT / 'analysis/isolated-prosthesis-photometric-review.ply'))['vertex']
world = np.stack([ply[k] for k in ('x', 'y', 'z')], axis=1).astype(float)
rgb = np.stack([ply[k] for k in ('red', 'green', 'blue')], axis=1)
cloud = ((world - origin) @ basis) * mm_per_unit
t = -cloud[:, 2]
gray = rgb.mean(axis=1)
radius = np.linalg.norm(cloud[:, :2], axis=1)
white_mask = (t >= 192) & (t < 311) & (gray >= 120) & (radius < 78)
black_mask = (t >= -58) & (t < 155) & (gray <= 100) & (radius < 90)
yellow_mask = (t >= 160) & (t < 205) & (rgb[:, 0] > 80) & (rgb[:, 1] > 65) & (rgb[:, 2] < 150)
white = cloud[white_mask]
black = cloud[black_mask]
yellow = cloud[yellow_mask]
print('observed points white/black/yellow:', len(white), len(black), len(yellow), flush=True)

mesh = trimesh.load_mesh(OUT / 'hunyuan31-original.stl', process=True)
zface = mesh.triangles_center[:, 2]
area = mesh.area_faces
rim_candidates = mesh.vertices[mesh.vertices[:, 2] >= .85]
rim_hull = rim_candidates[ConvexHull(rim_candidates[:, :2]).vertices]
rim_planar_distances = distance.cdist(rim_hull[:, :2], rim_hull[:, :2])
rim_i, rim_j = np.unravel_index(np.argmax(rim_planar_distances), rim_planar_distances.shape)
rim_outer_span_stl = float(rim_planar_distances[rim_i, rim_j])
measured_outer_span_mm = 120.0
calibrated_mm_per_stl_unit = measured_outer_span_mm / rim_outer_span_stl
print('outer top span native', rim_outer_span_stl, '-> scale', calibrated_mm_per_stl_unit, flush=True)

def sample_band(low, high, count, seed):
    weights = np.where((zface >= low) & (zface < high), area, 0.0)
    if not weights.any():
        raise ValueError('empty STL band')
    return trimesh.sample.sample_surface(mesh, count, face_weight=weights,
                                         seed=seed)[0]

mesh_white = sample_band(.29, .55, 30000, 1)
mesh_black = sample_band(.61, 1.125, 50000, 2)
mesh_yellow = sample_band(.54, .61, 10000, 3)
white_fit = white[rng.choice(len(white), min(18000, len(white)), replace=False)]

def transform(X, s, R, v):
    return s * (X @ R.T) + v

def rigid_at_scale(X, Y, scale):
    mx, my = X.mean(axis=0), Y.mean(axis=0)
    xc, yc = X - mx, Y - my
    u, singular, vt = np.linalg.svd(xc.T @ yc / len(X))
    rot = vt.T @ np.diag([1.0, 1.0, np.linalg.det(vt.T @ u.T)]) @ u.T
    trans = my - scale * (rot @ mx)
    return rot, trans

def residual(cloud_points, sample, s, R, v):
    tree = cKDTree(transform(sample, s, R, v))
    return tree.query(cloud_points, workers=-1)[0]

candidates = []
for scale_guess in (calibrated_mm_per_stl_unit,):
 for yaw_deg in range(0, 360, 30):
    yaw = np.deg2rad(yaw_deg)
    R = np.array([[np.cos(yaw), -np.sin(yaw), 0],
                  [np.sin(yaw),  np.cos(yaw), 0],
                  [0, 0, 1]], float)
    s = scale_guess
    v = np.median(white_fit, axis=0) - s * (R @ np.median(mesh_white, axis=0))
    v[2] = -180.0 - s * (R @ np.array([0.0, 0.05, 0.56]))[2]
    for iteration in range(25):
        tree = cKDTree(transform(mesh_white, s, R, v))
        dist, nearest = tree.query(white_fit, workers=-1)
        keep = dist <= np.quantile(dist, .78)
        new_R, new_v = rigid_at_scale(mesh_white[nearest[keep]], white_fit[keep], s)
        if np.degrees(np.arccos(np.clip(new_R[2, 2], -1, 1))) > 23:
            break
        R, v = new_R, new_v
        v[2] = -180.0 - s * (R @ np.array([0.0, 0.05, 0.56]))[2]
    wd = residual(white_fit, mesh_white, s, R, v)
    bd = residual(black[rng.choice(len(black), min(15000, len(black)), replace=False)],
                  mesh_black, s, R, v)
    record = dict(yaw_seed=yaw_deg, scale_mm_per_stl_unit=float(s),
                  white_median_mm=float(np.median(wd)), white_p80_mm=float(np.quantile(wd, .8)),
                  black_median_mm=float(np.median(bd)), black_p80_mm=float(np.quantile(bd, .8)),
                  R=R.tolist(), translation_mm=v.tolist())
    candidates.append(record)
    print(f'yaw seed {yaw_deg:3d}: scale={s:.1f} white med/p80={record["white_median_mm"]:.1f}/{record["white_p80_mm"]:.1f} '
          f'black med/p80={record["black_median_mm"]:.1f}/{record["black_p80_mm"]:.1f}', flush=True)

# The white shaft is nearly rotationally symmetric. A nearest-point score alone
# picks a wrong upper-rim lobe orientation (seed 120). Compare two orthogonal
# upper-rim silhouettes and retain seed 210, which puts the tall lobe on the
# same side as the calibrated cloud. Keep all other candidates in the report.
best = next(item for item in candidates if item['yaw_seed'] == 210)
best['orientation_choice'] = 'yaw seed 210 chosen by visual upper-rim lobe correspondence in side/front candidate montage; provisional'
s, R, v = best['scale_mm_per_stl_unit'], np.asarray(best['R']), np.asarray(best['translation_mm'])
for key, observed, model in [('white', white, mesh_white), ('black', black, mesh_black), ('yellow', yellow, mesh_yellow)]:
    dist = residual(observed, model, s, R, v)
    best[f'{key}_distance_mm'] = {q: float(np.quantile(dist, val))
                                  for q, val in [('p10', .1), ('median', .5), ('p80', .8), ('p90', .9)]}
    print(key, best[f'{key}_distance_mm'], flush=True)

up_model = R @ np.array([0.0, 0.0, 1.0])
best['stl_axis_in_cloud_up_frame'] = up_model.tolist()
best['axis_tilt_deg'] = float(np.degrees(np.arccos(np.clip(up_model[2], -1, 1))))
best['coordinate_frame'] = 'test4 isolated cloud, mm; Z is up (opposite isolation axis)'
best['mm_per_colmap_unit'] = mm_per_unit
best['fit_region'] = 'white shaft only: target t=192..311 mm, STL z=.29..55; 78% trimmed rigid ICP at trial scale'
best['scale_constraint'] = 'Fixed from measured 120 mm outer-to-outer widest upper opening; collar z=.56 anchored to cloud yellow transition t=180 mm'
best['physical_measurement'] = {
    'description': 'widest upper opening, outer edge to outer edge, horizontal XY projection',
    'measured_mm': measured_outer_span_mm,
    'stl_native_units': rim_outer_span_stl,
    'rim_point_1_stl_xyz': rim_hull[rim_i].tolist(),
    'rim_point_2_stl_xyz': rim_hull[rim_j].tolist(),
    'derived_mm_per_stl_unit': calibrated_mm_per_stl_unit,
    'full_3d_distance_between_rim_points_stl': float(np.linalg.norm(rim_hull[rim_i] - rim_hull[rim_j])),
}
best['warning'] = 'Approximate cloud-to-sampled-mesh distances, not certified fit tolerance. Cloud itself has gaps/outliers. Scale depends on landmark identification.'
best['section_bounds_mm'] = []
for label, zlo, zhi, observed, model_sample in [
    ('receiver_top', 0, 55, black, mesh_black),
    ('receiver_middle', -115, -65, black, mesh_black),
    ('shaft_middle', -260, -220, white, mesh_white),
]:
    model_local = transform(model_sample, s, R, v)
    a = observed[(observed[:, 2] >= zlo) & (observed[:, 2] < zhi)]
    b = model_local[(model_local[:, 2] >= zlo) & (model_local[:, 2] < zhi)]
    if len(a) < 50 or len(b) < 50:
        continue
    qa = np.quantile(a[:, :2], [.05, .5, .95], axis=0)
    qb = np.quantile(b[:, :2], [.05, .5, .95], axis=0)
    section = {'label': label, 'up_mm': [zlo, zhi],
               'colmap_xy_p05_p50_p95_mm': qa.round(2).tolist(),
               'stl_xy_p05_p50_p95_mm': qb.round(2).tolist(),
               'stl_minus_colmap_xy_p05_p50_p95_mm': (qb - qa).round(2).tolist(),
               'points_colmap': len(a), 'points_stl_sampled': len(b)}
    best['section_bounds_mm'].append(section)
    print('section', section, flush=True)
report = {'best': best, 'candidates': candidates,
          'source_stl': str(OUT / 'hunyuan31-original.stl'),
          'target_cloud': str(ROOT / 'analysis/isolated-prosthesis-photometric-review.ply'),
          'point_counts': {'white': len(white), 'black': len(black), 'yellow': len(yellow)}}
(OUT / 'comparison-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))

# Keep the original STL intact; export the registered copy in millimetres.
registered = mesh.copy()
registered.vertices = transform(mesh.vertices, s, R, v)
registered.export(OUT / 'hunyuan31-aligned-mm.ply')
trimesh.PointCloud(vertices=cloud, colors=rgb).export(OUT / 'test4-cloud-calibrated-mm.ply')

# Diagnostics: observed cloud and aligned mesh in the same calibrated frame.
def plot_overlay(name, axes, xlim, ylim):
    size = 1200
    im = Image.new('RGB', (size, size), (249, 249, 249))
    draw = ImageDraw.Draw(im)
    def xy(p):
        x = int((p[axes[0]] - xlim[0]) / (xlim[1] - xlim[0]) * (size - 1))
        y = size - 1 - int((p[axes[1]] - ylim[0]) / (ylim[1] - ylim[0]) * (size - 1))
        return x, y
    # show all subject points faintly, then registered model in magenta
    step = max(1, len(cloud) // 110000)
    for p, c in zip(cloud[::step], rgb[::step]):
        x, y = xy(p)
        if 0 <= x < size and 0 <= y < size:
            draw.point((x, y), fill=tuple(int(.6 * val + 95) for val in c))
    samples = transform(np.concatenate([mesh_white[::2], mesh_black[::2]], axis=0), s, R, v)
    for p in samples:
        x, y = xy(p)
        if 0 <= x < size and 0 <= y < size:
            draw.point((x, y), fill=(210, 15, 150))
    draw.text((20, 20), f'gray=color COLMAP point cloud  magenta=Hunyuan STL | fitted to white shaft | 200 mm bar scale',
              fill=(10, 10, 10))
    im.save(OUT / name)

plot_overlay('overlay-side.png', (0, 2), (-140, 140), (-355, 100))
plot_overlay('overlay-front.png', (1, 2), (-140, 140), (-355, 100))
print('BEST', best, flush=True)
