"""Inspect the generated STL and the calibrated test4 COLMAP cloud."""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from plyfile import PlyData
import trimesh

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
OUT = ROOT / 'hunyuan31-comparison'
cfg = json.loads((ROOT / 'analysis/isolation-config.json').read_text())
scale = json.loads((ROOT / 'analysis/scale-calibration.json').read_text())['mm_per_colmap_unit']
origin = np.array(cfg['origin_colmap'], float)
axis = np.array(cfg['axis_colmap'], float)
axis /= np.linalg.norm(axis)
xaxis = np.cross(axis, [1, 0, 0]); xaxis /= np.linalg.norm(xaxis)
yaxis = np.cross(axis, xaxis)
cloud = PlyData.read(str(ROOT / 'analysis/isolated-prosthesis-photometric-review.ply'))['vertex']
points = np.stack([cloud[a] for a in ('x', 'y', 'z')], axis=1).astype(float)
rgb = np.stack([cloud[a] for a in ('red', 'green', 'blue')], axis=1)
local = np.stack([(points - origin) @ xaxis,
                  (points - origin) @ yaxis,
                  (points - origin) @ axis], axis=1) * scale
stl = trimesh.load_mesh(OUT / 'hunyuan31-original.stl', process=True)
sv = stl.vertices

print('COLMAP isolated cloud', len(points), 'points, mm scale', scale)
print('cloud local bounds mm', np.round(np.quantile(local, [0.01, 0.5, 0.99], axis=0), 1))
print('STL', len(sv), 'vertices', len(stl.faces), 'faces, watertight', stl.is_watertight)
print('STL native bounds', np.round(stl.bounds, 4))
print('cloud bands along isolation axis (mm):')
for lo in np.arange(-60, 330, 30):
    subset = (local[:, 2] >= lo) & (local[:, 2] < lo + 30)
    if subset.sum() < 10:
        continue
    q = np.quantile(local[subset, :2], [.05, .5, .95], axis=0)
    brightness = rgb[subset].mean(axis=1)
    print(f'{lo:+4.0f}..{lo+30:+4.0f} n={subset.sum():6d} '
          f'x[5,50,95]={q[:,0].round(1)} y[5,50,95]={q[:,1].round(1)} '
          f'gray-med={np.median(brightness):.0f} dark-frac={(brightness<80).mean():.2f}')
print('STL bands along +Z (native units):')
for lo in np.arange(0, 1.11, .1):
    subset = (sv[:, 2] >= lo) & (sv[:, 2] < lo + .1)
    if subset.sum() < 10:
        continue
    q = np.quantile(sv[subset, :2], [.05, .5, .95], axis=0)
    print(f'{lo:.1f}..{lo+.1:.1f} n={subset.sum():5d} x={q[:,0].round(3)} y={q[:,1].round(3)}')

def draw_scatter(name, xyz, colors, xy_axes, limits, nmax=90000):
    dim = 1000
    canvas = Image.new('RGB', (dim, dim), (235, 235, 235))
    pixels = canvas.load()
    idx = np.linspace(0, len(xyz) - 1, min(nmax, len(xyz))).astype(int)
    for i in idx:
        xx = int((xyz[i, xy_axes[0]] - limits[0][0]) / (limits[0][1] - limits[0][0]) * (dim - 1))
        yy = dim - 1 - int((xyz[i, xy_axes[1]] - limits[1][0]) / (limits[1][1] - limits[1][0]) * (dim - 1))
        if 0 <= xx < dim and 0 <= yy < dim:
            pixels[xx, yy] = tuple(int(c) for c in colors[i])
    canvas.save(OUT / name)

draw_scatter('cloud-side.png', local, rgb, (0, 2), ((-120, 120), (-90, 360)))
draw_scatter('cloud-front.png', local, rgb, (1, 2), ((-120, 120), (-90, 360)))
