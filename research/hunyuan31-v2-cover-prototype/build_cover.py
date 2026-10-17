"""Build a provisional C sleeve from the scaled Hunyuan mesh's exterior envelope.

This is a geometric inspection prototype. The mesh and the registered STL share
the test4 millimetre coordinate frame. It does not establish clinical fit.
"""

import json
import struct
from pathlib import Path

import numpy as np
from scipy import ndimage
import trimesh

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
INPUT = ROOT / 'hunyuan31-v2-comparison'
OUT = ROOT / 'hunyuan31-v2-cover-prototype'
OUT.mkdir(parents=True, exist_ok=True)
REPORT = json.loads((INPUT / 'comparison-report.json').read_text())
ALIGN = REPORT['best']
SCALE = float(ALIGN['scale_mm_per_stl_unit'])
R = np.asarray(ALIGN['R'], float)
TRANSLATION = np.asarray(ALIGN['translation_mm'], float)

DEFAULT_CONFIG = {
    'source_stl': str(INPUT / 'hunyuan31-v2-original.stl'),
    'measured_top_outer_width_mm': 120.0,
    'measured_front_shaft_width_mm': 80.0,
    'cover_bottom_stl_z': 0.47,
    'source_rim_band_min_stl_z': 0.88,
    'top_setback_mm': 12.0,
    'opening_center_native_angle_deg': 0.0,  # +X, the bolt side
    'opening_angle_deg': 72.0,
    'nominal_clearance_mm': 8.0,
    'wall_mm': 3.0,
    'z_sampling_step_mm': 5.0,
    'angle_sampling_deg': 3.0,
    'shell_z_sections': 82,
    'shell_angular_sections': 121,
}
config_path = OUT / 'config.json'
if config_path.exists():
    CONFIG = json.loads(config_path.read_text())
else:
    CONFIG = DEFAULT_CONFIG
    config_path.write_text(json.dumps(CONFIG, indent=2) + '\n')

stl_path = Path(CONFIG['source_stl'])
with stl_path.open('rb') as f:
    head = f.read(84)
face_count = struct.unpack_from('<I', head, 80)[0]
dtype = np.dtype([('normal', '<f4', (3,)), ('vertex', '<f4', (3, 3)),
                  ('attribute', '<u2')])
stl = np.memmap(stl_path, dtype=dtype, mode='r', offset=84, shape=(face_count,))
points = stl['vertex'].reshape(-1, 3)

# Cross-section envelopes use only the shaft/receiver. Lower shoe and the
# invented hand lie below the starting plane and never enter the measurements.
z0 = CONFIG['cover_bottom_stl_z']
z_grid = np.arange(z0, 1.105, CONFIG['z_sampling_step_mm'] / SCALE)
n_angles = int(round(360 / CONFIG['angle_sampling_deg']))
angles = 2 * np.pi * np.arange(n_angles) / n_angles
center = np.empty((len(z_grid), 2), dtype=float)
radial = np.full((len(z_grid), n_angles), np.nan, dtype=float)
counts = np.zeros((len(z_grid), n_angles), dtype=int)
band_half = 2.5 / SCALE

for k, z in enumerate(z_grid):
    band = points[np.abs(points[:, 2] - z) <= band_half, :2]
    if len(band) < 200:
        raise RuntimeError(f'Too few surface vertices at z={z:.4f}')
    q = np.quantile(band, [.05, .95], axis=0)
    center[k] = (q[0] + q[1]) / 2
    delta = band - center[k]
    a = np.mod(np.arctan2(delta[:, 1], delta[:, 0]), 2*np.pi)
    bins = np.minimum((a * n_angles / (2*np.pi)).astype(int), n_angles-1)
    rho = np.linalg.norm(delta, axis=1)
    for j in range(n_angles):
        selected = rho[bins == j]
        counts[k, j] = len(selected)
        if len(selected) >= 8:
            radial[k, j] = np.quantile(selected, .99)

# Fill sparse upper-rim sectors from adjacent heights, then adjacent angles.
for j in range(n_angles):
    good = np.isfinite(radial[:, j])
    if good.sum() < 20:
        raise RuntimeError(f'Insufficient body surface for angular sector {j}')
    radial[:, j] = np.interp(z_grid, z_grid[good], radial[good, j])
center = ndimage.gaussian_filter1d(center, 1.2, axis=0)
smoothed = ndimage.gaussian_filter(
    ndimage.maximum_filter(radial, size=(3, 3), mode=('nearest', 'wrap')),
    sigma=(1.1, 1.2), mode=('nearest', 'wrap'))
envelope = np.maximum(smoothed, radial)

# Estimate the irregular opening edge by angular sector. A setback leaves the
# original socket lip uncovered, avoiding contact with its inner opening.
rim = points[points[:, 2] >= CONFIG['source_rim_band_min_stl_z']]
top_center = center[np.argmin(np.abs(z_grid - .92))]
a_rim = np.mod(np.arctan2(rim[:, 1]-top_center[1], rim[:, 0]-top_center[0]), 2*np.pi)
rim_bins = np.minimum((a_rim * n_angles/(2*np.pi)).astype(int), n_angles-1)
rim_top = np.full(n_angles, np.nan)
for j in range(n_angles):
    zs = rim[rim_bins == j, 2]
    if len(zs) >= 15:
        rim_top[j] = np.quantile(zs, .99)
valid = np.isfinite(rim_top)
if valid.sum() < n_angles * .9:
    raise RuntimeError('Socket rim lacks sufficient angular coverage')
extended = np.r_[np.flatnonzero(valid)-n_angles,
                 np.flatnonzero(valid), np.flatnonzero(valid)+n_angles]
values = np.tile(rim_top[valid], 3)
rim_top = np.interp(np.arange(n_angles), extended, values)
rim_top = ndimage.gaussian_filter1d(rim_top, 2.0, mode='wrap')
top_z = rim_top - CONFIG['top_setback_mm']/SCALE
top_z = np.clip(top_z, .945, 1.08)

opening_half = np.deg2rad(CONFIG['opening_angle_deg']/2)
opening_center = np.deg2rad(CONFIG['opening_center_native_angle_deg'])
shell_angles = np.linspace(opening_center+opening_half,
                           opening_center+2*np.pi-opening_half,
                           CONFIG['shell_angular_sections'])
shell_t = np.linspace(0, 1, CONFIG['shell_z_sections'])
native = np.empty((2, len(shell_t), len(shell_angles), 3), dtype=np.float64)

def interpolate_periodic(values, theta):
    return np.interp(np.mod(theta, 2*np.pi), np.r_[angles, 2*np.pi],
                     np.r_[values, values[0]])

for j, theta in enumerate(shell_angles):
    top = interpolate_periodic(top_z, theta)
    zs = z0 + shell_t * (top-z0)
    cx = np.interp(zs, z_grid, center[:, 0])
    cy = np.interp(zs, z_grid, center[:, 1])
    env_at_angle = np.array([interpolate_periodic(row, theta) for row in envelope])
    rs = np.interp(zs, z_grid, env_at_angle)
    for side, extra in enumerate((CONFIG['nominal_clearance_mm'],
                                  CONFIG['nominal_clearance_mm']+CONFIG['wall_mm'])):
        radius = rs + extra/SCALE
        native[side, :, j, 0] = cx + radius*np.cos(theta)
        native[side, :, j, 1] = cy + radius*np.sin(theta)
        native[side, :, j, 2] = zs

vertices = (SCALE * (native.reshape(-1, 3) @ R.T) + TRANSLATION).astype(np.float32)
nz, na = len(shell_t), len(shell_angles)

def index(side, iz, ia):
    return (side*nz + iz)*na + ia

faces = []
def quad(a, b, c, d):
    faces.append((a, b, c))
    faces.append((a, c, d))

for iz in range(nz-1):
    for ia in range(na-1):
        quad(index(1,iz,ia), index(1,iz+1,ia),
             index(1,iz+1,ia+1), index(1,iz,ia+1))
        quad(index(0,iz,ia+1), index(0,iz+1,ia+1),
             index(0,iz+1,ia), index(0,iz,ia))
for ia in range(na-1):
    quad(index(0,0,ia), index(1,0,ia), index(1,0,ia+1), index(0,0,ia+1))
    quad(index(0,nz-1,ia+1), index(1,nz-1,ia+1),
         index(1,nz-1,ia), index(0,nz-1,ia))
for iz in range(nz-1):
    quad(index(0,iz,0), index(0,iz+1,0),
         index(1,iz+1,0), index(1,iz,0))
    quad(index(1,iz,na-1), index(1,iz+1,na-1),
         index(0,iz+1,na-1), index(0,iz,na-1))

mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces), process=True)
trimesh.repair.fix_normals(mesh)
if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
    raise RuntimeError(f'Cover mesh invalid: watertight={mesh.is_watertight}, '
                       f'winding={mesh.is_winding_consistent}, volume={mesh.volume}')
mesh.export(OUT/'cover_trial.stl')

# Evaluate the radial gap to the input mesh only in the proposed cover area.
sample = points[(points[:, 2] >= z0) & (points[:, 2] <= 1.08)][::9]
local_center = np.column_stack([np.interp(sample[:, 2], z_grid, center[:, k])
                                for k in range(2)])
delta = sample[:, :2] - local_center
theta = np.mod(np.arctan2(delta[:, 1], delta[:, 0]), 2*np.pi)
from_opening_center = np.abs(np.arctan2(np.sin(theta-opening_center),
                                       np.cos(theta-opening_center)))
applicable = (from_opening_center >= opening_half) & \
             (sample[:, 2] <= interpolate_periodic(top_z, theta))
sample, theta, delta = sample[applicable], theta[applicable], delta[applicable]
zi = (sample[:, 2]-z_grid[0])/(z_grid[1]-z_grid[0])
ai = theta*n_angles/(2*np.pi)
envelope_at_sample = ndimage.map_coordinates(envelope, [zi, ai], order=1,
                                               mode='grid-wrap')
gap_mm = (envelope_at_sample - np.linalg.norm(delta, axis=1))*SCALE + \
         CONFIG['nominal_clearance_mm']

# A short coupon at the user's 80 mm front-width measurement plane gives a
# cheaper physical fit check before printing the entire sleeve.
coupon_center_z = .65 - 30.0/SCALE
coupon_zs = coupon_center_z + np.array([-10.0, 10.0])/SCALE
coupon_native = np.empty((2, 2, na, 3), dtype=float)
for iz, z in enumerate(coupon_zs):
    cx = np.interp(z, z_grid, center[:, 0])
    cy = np.interp(z, z_grid, center[:, 1])
    for ia, theta in enumerate(shell_angles):
        env_at_angle = np.array([interpolate_periodic(row, theta) for row in envelope])
        r = np.interp(z, z_grid, env_at_angle)
        for side, extra in enumerate((CONFIG['nominal_clearance_mm'],
                                      CONFIG['nominal_clearance_mm']+CONFIG['wall_mm'])):
            rr = r + extra/SCALE
            coupon_native[side,iz,ia] = (cx+rr*np.cos(theta),
                                          cy+rr*np.sin(theta), z)
coupon_vertices = (SCALE*(coupon_native.reshape(-1,3)@R.T)+TRANSLATION).astype(np.float32)
def coupon_index(side, iz, ia):
    return (side*2+iz)*na+ia
coupon_faces = []
def coupon_quad(a,b,c,d):
    coupon_faces.extend(((a,b,c),(a,c,d)))
for ia in range(na-1):
    coupon_quad(coupon_index(1,0,ia),coupon_index(1,1,ia),
                coupon_index(1,1,ia+1),coupon_index(1,0,ia+1))
    coupon_quad(coupon_index(0,0,ia+1),coupon_index(0,1,ia+1),
                coupon_index(0,1,ia),coupon_index(0,0,ia))
    coupon_quad(coupon_index(0,0,ia),coupon_index(1,0,ia),
                coupon_index(1,0,ia+1),coupon_index(0,0,ia+1))
    coupon_quad(coupon_index(0,1,ia+1),coupon_index(1,1,ia+1),
                coupon_index(1,1,ia),coupon_index(0,1,ia))
for iz in range(1):
    coupon_quad(coupon_index(0,iz,0),coupon_index(0,iz+1,0),
                coupon_index(1,iz+1,0),coupon_index(1,iz,0))
    coupon_quad(coupon_index(1,iz,na-1),coupon_index(1,iz+1,na-1),
                coupon_index(0,iz+1,na-1),coupon_index(0,iz,na-1))
coupon = trimesh.Trimesh(vertices=coupon_vertices,faces=np.asarray(coupon_faces),process=True)
trimesh.repair.fix_normals(coupon)
if not coupon.is_volume or len(coupon.split()) != 1:
    raise RuntimeError('20 mm coupon is not one closed printable volume')
coupon.export(OUT/'fit_coupon_20mm.stl')

report = {
    'status': 'PROVISIONAL GEOMETRY FOR VISUAL REVIEW AND FIT COUPON',
    'source': str(stl_path),
    'source_face_count': face_count,
    'cover_face_count': int(len(mesh.faces)),
    'coordinate_frame': 'same calibrated test4 millimetre frame as hunyuan31-v2-aligned-mm.stl',
    'cover_bottom_native_z': z0,
    'cover_top_native_z_min_max': [float(top_z.min()), float(top_z.max())],
    'nominal_clearance_mm': CONFIG['nominal_clearance_mm'],
    'wall_mm': CONFIG['wall_mm'],
    'opening_angle_deg': CONFIG['opening_angle_deg'],
    'opening_center_native_angle_deg': CONFIG['opening_center_native_angle_deg'],
    'opening_side': 'native STL +X at 0 degrees, approximately the bolt side',
    'source_sample_count_for_gap': int(len(gap_mm)),
    'radial_gap_to_source_mesh_mm': {
        'min': float(gap_mm.min()),
        'p01': float(np.quantile(gap_mm, .01)),
        'median': float(np.median(gap_mm)),
        'negative_fraction': float(np.mean(gap_mm < 0)),
    },
    'watertight': bool(mesh.is_watertight),
    'winding_consistent': bool(mesh.is_winding_consistent),
    'volume_mm3': float(mesh.volume),
    'coupon_height_mm': 20.0,
    'coupon_face_count': int(len(coupon.faces)),
    'coupon_is_volume': bool(coupon.is_volume),
    'limitations': [
        'Input AI mesh has unverified local geometry and invented shoe/hand features.',
        'Clearance is against the AI mesh, not against the physical prosthesis.',
        'No fastener, retention feature, decorative perforation or bolt-specific cutout.',
        'Do not use as a final fitted cover without physical test coupons and inspection.',
    ],
}
(OUT/'build_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
