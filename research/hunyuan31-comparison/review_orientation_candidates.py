"""Show plausible yaw solutions at the measured 120 mm outer-opening scale."""

import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from plyfile import PlyData
import trimesh

root = Path('/Volumes/extra/workspace1/projects/test4/hunyuan31-comparison')
report = json.loads((root / 'comparison-report.json').read_text())
candidates = {c['yaw_seed']: c for c in report['candidates']}
selected = (90, 120, 150, 210, 240, 270)
ply = PlyData.read(str(root / 'test4-cloud-calibrated-mm.ply'))['vertex']
cloud = np.stack([ply[k] for k in ('x', 'y', 'z')], axis=1)
rgb = np.stack([ply[k] for k in ('red', 'green', 'blue')], axis=1)
dark = rgb.mean(axis=1) < 105
cloud = cloud[dark & (cloud[:, 2] > -175)]
mesh = trimesh.load_mesh(root / 'hunyuan31-original.stl', process=True)
mask = mesh.triangles_center[:, 2] > .62
weight = np.where(mask, mesh.area_faces, 0.0)
surface = trimesh.sample.sample_surface(mesh, 25000, face_weight=weight, seed=55)[0]

width, height = 480, 480
overall = Image.new('RGB', (width * 3, height * 4), 'white')
for row, yaw in enumerate(selected):
    c = candidates[yaw]
    s, R, v = c['scale_mm_per_stl_unit'], np.asarray(c['R']), np.asarray(c['translation_mm'])
    pts = s * (surface @ R.T) + v
    for k, (axes, xlim, ylim, label) in enumerate([
        ((0, 2), (-135, 135), (-180, 95), 'side'),
        ((1, 2), (-135, 135), (-180, 95), 'front'),
    ]):
        im = Image.new('RGB', (width, height), (248, 248, 248))
        dr = ImageDraw.Draw(im)
        def xy(p):
            x = int((p[axes[0]] - xlim[0]) / (xlim[1] - xlim[0]) * (width-1))
            y = height-1-int((p[axes[1]] - ylim[0]) / (ylim[1] - ylim[0]) * (height-1))
            return x, y
        for p in cloud[::3]:
            x, y = xy(p)
            if 0 <= x < width and 0 <= y < height:
                dr.point((x, y), fill=(135, 135, 135))
        for p in pts[::2]:
            x, y = xy(p)
            if 0 <= x < width and 0 <= y < height:
                dr.point((x, y), fill=(230, 20, 145))
        dr.text((10, 10), f'yaw seed {yaw} | {label} | STL pink cloud gray', fill=(0,0,0))
        overall.paste(im, ((row % 3) * width, ((row // 3)*2 + k) * height))
overall.save(root / 'orientation-candidates.png')
