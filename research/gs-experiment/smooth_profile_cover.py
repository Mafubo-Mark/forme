"""Test a smooth, silhouette-constrained parametric sleeve (review only)."""
import json
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
import trimesh

BASE = Path('/Volumes/extra/workspace1/projects/test4/gs-experiment')
OUT = BASE / 'cad-v6-smooth-preview'
OUT.mkdir(exist_ok=True)
d = np.load(BASE / 'cad-v5-silhouette-preview/silhouette_volume.npz')
occupancy = d['support']
grid = d['x_mm']
heights = d['z_mm']
sec = json.loads((BASE / 'cad-v4/sections.json').read_text())
stations = sec['stations']
station_z = np.array([s['height_mm'] for s in stations])
cx = np.interp(heights, station_z, [s['center_x_mm'] for s in stations])
cy = np.interp(heights, station_z, [s['center_y_mm'] for s in stations])
angles = np.deg2rad(np.arange(0, 360, 2.0))
probe_r = np.arange(0, 115, 1.0)
raw_r = np.zeros((len(heights), len(angles)), dtype=np.float32)
for k in range(len(heights)):
    xp = cx[k] + np.cos(angles)[:, None] * probe_r
    yp = cy[k] + np.sin(angles)[:, None] * probe_r
    xi = (xp - grid[0]) / (grid[1] - grid[0])
    yi = (yp - grid[0]) / (grid[1] - grid[0])
    hit = ndi.map_coordinates(occupancy[k].astype(np.float32), [yi, xi],
                              order=1, mode='constant') > .5
    raw_r[k] = np.max(np.where(hit, probe_r[None, :], 0), axis=1)

# A median filter removes single-view mask spikes before the low-frequency fit.
valid = heights <= 305
raw_body = raw_r[valid].copy()
for j in range(len(angles)):
    col = raw_body[:, j]
    good = col > 22
    if good.sum() < .8 * len(col):
        raise RuntimeError(f'Insufficient radial evidence for angle {np.rad2deg(angles[j]):.0f}')
    raw_body[:, j] = np.interp(heights[valid], heights[valid][good], col[good])
radii = ndi.gaussian_filter(ndi.median_filter(raw_body, size=(7, 5), mode='nearest'),
                            sigma=(5, 3), mode=('nearest', 'wrap'))

# The top edge is taken from the highest supported photographed silhouette
# at each angular direction; isolated axial hits are discarded by filtering.
top_candidates = np.where(raw_r > 30, heights[:, None], -1)
top_z = np.max(top_candidates, axis=0)
top_z = ndi.gaussian_filter1d(ndi.median_filter(top_z, size=7, mode='wrap'),
                             2.5, mode='wrap')
top_z = np.clip(top_z - 9, 290, 355)
print('top rim range (mm)', float(top_z.min()), float(top_z.max()), flush=True)

# C opening opposite the bolt; all arrays share one angular vertex sequence.
keep = np.flatnonzero((angles >= np.deg2rad(14)) &
                      (angles <= 2*np.pi - np.deg2rad(14)))
theta = angles[keep]
rim = top_z[keep]
nt, nz = len(theta), 90
t = np.linspace(0, 1, nz)
vertex = np.empty((2, nz, nt, 3), np.float32)
for j, a in enumerate(theta):
    zs = heights[0] + t * (rim[j] - heights[0])
    contour = np.interp(np.minimum(zs, 305), heights[valid], radii[:, keep[j]])
    xcent = np.interp(zs, station_z, [s['center_x_mm'] for s in stations])
    ycent = np.interp(zs, station_z, [s['center_y_mm'] for s in stations])
    for side, offset in enumerate((5.0, 8.0)):
        vertex[side, :, j, 0] = xcent + (contour + offset) * np.cos(a)
        vertex[side, :, j, 1] = ycent + (contour + offset) * np.sin(a)
        vertex[side, :, j, 2] = zs

verts = vertex.reshape((-1, 3))
def idx(side, iz, ia):
    return (side * nz + iz) * nt + ia
faces = []
for side in range(2):
    for iz in range(nz-1):
        for ia in range(nt-1):
            a, b, c, e = idx(side, iz, ia), idx(side, iz+1, ia), idx(side, iz+1, ia+1), idx(side, iz, ia+1)
            faces.extend(((a,b,c),(a,c,e)) if side else ((a,c,b),(a,e,c)))
for iz in (0, nz-1):
    for ia in range(nt-1):
        a,b,c,e = idx(0,iz,ia),idx(1,iz,ia),idx(1,iz,ia+1),idx(0,iz,ia+1)
        faces.extend(((a,b,c),(a,c,e)) if iz == 0 else ((a,c,b),(a,e,c)))
for ia in (0, nt-1):
    for iz in range(nz-1):
        a,b,c,e = idx(0,iz,ia),idx(1,iz,ia),idx(1,iz+1,ia),idx(0,iz+1,ia)
        faces.extend(((a,c,b),(a,e,c)) if ia == 0 else ((a,b,c),(a,c,e)))
mesh = trimesh.Trimesh(vertices=verts, faces=np.asarray(faces), process=True)
if not mesh.is_watertight:
    raise RuntimeError('Parametric sleeve is not watertight')
if mesh.volume < 0:
    mesh.invert()
if not mesh.is_winding_consistent or mesh.volume <= 0:
    raise RuntimeError('Parametric sleeve has inconsistent or inward faces')
mesh.export(OUT / 'smooth_sleeve_preview.stl')
report = {'status': 'REJECTED AS GEOMETRY EVIDENCE — NOT FOR FIT OR PRINT',
          'method': 'silhouette-derived polar sections with robust angular and axial smoothing',
          'source': 'COLMAP-calibrated multi-view subject masks; 3DGS visual reference',
          'top_rim_min_max_mm': [float(top_z.min()),float(top_z.max())],
          'watertight': bool(mesh.is_watertight),
          'winding_consistent': bool(mesh.is_winding_consistent),
          'volume_mm3_preview': float(mesh.volume),
          'warnings': ['Input alpha masks were generated from the same COLMAP dense cloud; the apparent silhouette check is not independent.',
                       'The centerline is reused from cad-v4, so this is not a new metric reconstruction.',
                       'The upper rim, hidden concavities and fit clearance are not validated.',
                       'No bolt hole has been cut; bolt dimensions and position must be measured.',
                       'No production STEP is exported; physical dimensions and test coupons are still required.']}
(OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print('Wrote',OUT/'smooth_sleeve_preview.stl','faces',len(mesh.faces),flush=True)
