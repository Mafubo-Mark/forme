"""Make a reproducible, lightweight visual sample of the calibrated cloud."""

from pathlib import Path
import numpy as np
from plyfile import PlyData

root = Path('/Volumes/extra/workspace1/projects/test4/hunyuan31-comparison')
v = PlyData.read(str(root / 'test4-cloud-calibrated-mm.ply'))['vertex']
points = np.stack([v[k] for k in ('x', 'y', 'z')], axis=1)
colors = np.stack([v[k] for k in ('red', 'green', 'blue')], axis=1)
gray = colors.mean(axis=1)
rng = np.random.default_rng(20260929)

groups = {
    'receiver_cloud': (points[:, 2] > -165) & (gray < 105),
    'tape_cloud': (points[:, 2] >= -210) & (points[:, 2] < -155)
                  & (colors[:, 0] > 80) & (colors[:, 1] > 65) & (colors[:, 2] < 150),
    'shaft_cloud': (points[:, 2] < -185) & (gray > 120),
}
samples = {}
for name, mask in groups.items():
    pts = points[mask]
    count = min(len(pts), {'receiver_cloud': 25000, 'tape_cloud': 5000,
                           'shaft_cloud': 13000}[name])
    selected = rng.choice(len(pts), count, replace=False)
    samples[name] = pts[selected].astype(np.float32)
    print(name, len(pts), 'source ->', count, 'review points')
np.savez_compressed(root / 'blender-review-cloud-sample.npz', **samples)
