"""Compare the 1.5M-face Hunyuan STL with the test4 calibrated cloud.

The full STL is streamed as binary triangles. Only upper receiver and shaft
surface samples are used for registration, excluding shoe/hand hallucinations.
"""

import json
import shutil
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from plyfile import PlyData
from scipy.spatial import ConvexHull, cKDTree, distance

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
OUT = ROOT / 'hunyuan31-v2-comparison'
STL = OUT / 'hunyuan31-v2-original.stl'
CLOUD = ROOT / 'hunyuan31-comparison/test4-cloud-calibrated-mm.ply'
SEED = 20260929
rng = np.random.default_rng(SEED)

with STL.open('rb') as f:
    head = f.read(84)
triangles = struct.unpack_from('<I', head, 80)[0]
dtype = np.dtype([('normal', '<f4', (3,)), ('vertex', '<f4', (3, 3)),
                  ('attribute', '<u2')])
stl = np.memmap(STL, dtype=dtype, mode='r', offset=84, shape=(triangles,))
faces = stl['vertex']
all_points = faces.reshape(-1, 3)
top = all_points[all_points[:, 2] >= .85]
top_hull = top[ConvexHull(top[:, :2]).vertices]
diameters = distance.cdist(top_hull[:, :2], top_hull[:, :2])
i, j = np.unravel_index(np.argmax(diameters), diameters.shape)
native_span = float(diameters[i, j])
scale = 120.0 / native_span
print('STL', triangles, 'faces, top outer XY span', native_span,
      '->', scale, 'mm/native unit', flush=True)

ply = PlyData.read(str(CLOUD))['vertex']
cloud = np.stack([ply[k] for k in ('x', 'y', 'z')], axis=1).astype(float)
rgb = np.stack([ply[k] for k in ('red', 'green', 'blue')], axis=1)
t = -cloud[:, 2]
gray = rgb.mean(axis=1)
radius = np.linalg.norm(cloud[:, :2], axis=1)
white_mask = (t >= 192) & (t < 311) & (gray >= 120) & (radius < 78)
black_mask = (t >= -58) & (t < 155) & (gray <= 100) & (radius < 90)
yellow_mask = (t >= 160) & (t < 205) & (rgb[:, 0] > 80) & (rgb[:, 1] > 65) & (rgb[:, 2] < 150)
observed = {'white': cloud[white_mask], 'black': cloud[black_mask],
            'yellow': cloud[yellow_mask]}
print('cloud white/black/yellow counts', {k:len(v) for k,v in observed.items()}, flush=True)

e1 = faces[:, 1] - faces[:, 0]
e2 = faces[:, 2] - faces[:, 0]
area = 0.5 * np.linalg.norm(np.cross(e1, e2), axis=1)
face_z = faces[:, :, 2].mean(axis=1)

def sample_band(low, high, count):
    ids = np.flatnonzero((face_z >= low) & (face_z < high) & (area > 0))
    weights = area[ids].astype(float)
    selected = rng.choice(ids, count, replace=True, p=weights / weights.sum())
    tri = faces[selected].astype(float)
    u = np.sqrt(rng.random(count))
    v = rng.random(count)
    return ((1-u)[:, None] * tri[:, 0] +
            (u*(1-v))[:, None] * tri[:, 1] +
            (u*v)[:, None] * tri[:, 2])

model = {'white': sample_band(.44, .65, 30000),
         'black': sample_band(.71, 1.111, 50000),
         'yellow': sample_band(.65, .72, 10000)}
white_fit = observed['white'][rng.choice(len(observed['white']),
                                          min(18000, len(observed['white'])), replace=False)]
black_fit = observed['black'][rng.choice(len(observed['black']),
                                          min(15000, len(observed['black'])), replace=False)]

def transform(X, R, v):
    return scale * (X @ R.T) + v

def rigid_at_scale(X, Y):
    mx, my = X.mean(axis=0), Y.mean(axis=0)
    u, _, vt = np.linalg.svd((X-mx).T @ (Y-my) / len(X))
    rot = vt.T @ np.diag([1, 1, np.linalg.det(vt.T @ u.T)]) @ u.T
    trans = my - scale * (rot @ mx)
    return rot, trans

def nearest(observed_points, model_points, R, v):
    tree = cKDTree(transform(model_points, R, v))
    return tree.query(observed_points, workers=-1)[0]

candidates = []
collar = np.array([0.0, 0.05, .68])
for yaw_deg in range(0, 360, 30):
    yaw = np.deg2rad(yaw_deg)
    R = np.array([[np.cos(yaw), -np.sin(yaw), 0],
                  [np.sin(yaw), np.cos(yaw), 0],
                  [0, 0, 1]], float)
    v = np.median(white_fit, axis=0) - scale * (R @ np.median(model['white'], axis=0))
    v[2] = -180.0 - scale * (R @ collar)[2]
    for _ in range(25):
        tree = cKDTree(transform(model['white'], R, v))
        d, idx = tree.query(white_fit, workers=-1)
        keep = d <= np.quantile(d, .78)
        trial_R, trial_v = rigid_at_scale(model['white'][idx[keep]], white_fit[keep])
        if np.degrees(np.arccos(np.clip(trial_R[2, 2], -1, 1))) > 23:
            break
        R, v = trial_R, trial_v
        v[2] = -180.0 - scale * (R @ collar)[2]
    dw = nearest(white_fit, model['white'], R, v)
    db = nearest(black_fit, model['black'], R, v)
    result = {'yaw_seed': yaw_deg, 'scale_mm_per_stl_unit': scale,
              'white_median_mm': float(np.median(dw)),
              'white_p80_mm': float(np.quantile(dw, .8)),
              'black_median_mm': float(np.median(db)),
              'black_p80_mm': float(np.quantile(db, .8)),
              'R': R.tolist(), 'translation_mm': v.tolist()}
    candidates.append(result)
    print('candidate', yaw_deg, 'white', result['white_median_mm'],
          'black', result['black_median_mm'], flush=True)

best = min(candidates, key=lambda c: c['white_median_mm'] + .2*c['white_p80_mm'] + .2*c['black_median_mm'])
R, v = np.asarray(best['R']), np.asarray(best['translation_mm'])
for key in observed:
    d = nearest(observed[key], model[key], R, v)
    best[key + '_distance_mm'] = {'median': float(np.median(d)),
                                 'p90': float(np.quantile(d, .9))}
best['axis_tilt_deg'] = float(np.degrees(np.arccos(np.clip(R[2,2], -1, 1))))
measurement = {'physical_top_outer_width_mm': 120.0,
               'model_top_outer_xy_span_units': native_span,
               'derived_mm_per_stl_unit': scale,
               'point_1_stl_xyz': top_hull[i].tolist(),
               'point_2_stl_xyz': top_hull[j].tolist(),
               'direct_3d_chord_native_units': float(np.linalg.norm(top_hull[i]-top_hull[j])),
               'definition': 'widest upper outer edge in horizontal XY projection, z >= 0.85'}
report = {'input_stl': str(STL), 'reference_cloud': str(CLOUD),
          'face_count': triangles, 'measurement': measurement,
          'best': best, 'candidates': candidates,
          'registration': 'white shaft, rigid ICP at physically fixed scale; collar z=.68 aligned to cloud yellow band t=180 mm',
          'warning': 'One-way point-cloud-to-sampled-mesh distances; affected by point cloud gaps/outliers, landmark semantics and yaw ambiguity. Not a fit tolerance.'}
(OUT / 'comparison-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))

def overlay(name, axes, xlim, ylim):
    size = 1200
    im = Image.new('RGB', (size,size), (249,249,249))
    dr = ImageDraw.Draw(im)
    def xy(p):
        x = int((p[axes[0]]-xlim[0])/(xlim[1]-xlim[0])*(size-1))
        y = size-1-int((p[axes[1]]-ylim[0])/(ylim[1]-ylim[0])*(size-1))
        return x,y
    for p,c in zip(cloud[::2],rgb[::2]):
        x,y=xy(p)
        if 0<=x<size and 0<=y<size:
            dr.point((x,y),fill=tuple(int(.6*a+95) for a in c))
    upper=np.concatenate([model['white'][::2],model['black'][::2]])
    for p in transform(upper,R,v):
        x,y=xy(p)
        if 0<=x<size and 0<=y<size:
            dr.point((x,y),fill=(210,15,150))
    dr.text((15,15),'test4 COLMAP cloud=color | Hunyuan 1.5M STL=magenta | top outer width=120mm',fill=(0,0,0))
    im.save(OUT/name)

overlay('overlay-side.png',(0,2),(-140,140),(-355,100))
overlay('overlay-front.png',(1,2),(-140,140),(-355,100))

# Transform full-resolution binary STL directly, retaining all input faces.
aligned_stl = OUT / 'hunyuan31-v2-aligned-mm.stl'
shutil.copyfile(STL, aligned_stl)
dst = np.memmap(aligned_stl,dtype=dtype,mode='r+',offset=84,shape=(triangles,))
chunk = 50000
for start in range(0,triangles,chunk):
    end=min(start+chunk,triangles)
    dst['vertex'][start:end] = transform(np.asarray(stl['vertex'][start:end],dtype=float),R,v).astype(np.float32)
    dst['normal'][start:end] = (np.asarray(stl['normal'][start:end],dtype=float)@R.T).astype(np.float32)
dst.flush()
print('BEST',best,flush=True)
