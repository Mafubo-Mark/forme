"""Show where diagnostic z levels fall in original camera images."""
from pathlib import Path
import json
import cv2
import numpy as np
import pycolmap

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
OUT = ROOT / 'independent-silhouette'
roi = json.loads((ROOT / 'analysis/isolation-config.json').read_text())
scale = json.loads((ROOT / 'analysis/scale-calibration.json').read_text())['mm_per_colmap_unit']
origin = np.array(roi['origin_colmap'])
axis = np.array(roi['axis_colmap'])
axis /= np.linalg.norm(axis)
rec = pycolmap.Reconstruction(str(ROOT / 'reconstruction/dense/sparse'))
names = {'frame_00004.jpg', 'frame_00032.jpg', 'frame_00040.jpg', 'frame_00075.jpg'}
for im in rec.images.values():
    if im.name not in names:
        continue
    cam = rec.cameras[im.camera_id]
    pose = np.asarray(im.cam_from_world().matrix())
    photo = cv2.imread(str(ROOT / 'reconstruction/dense/images' / im.name))
    for z_mm in [-45, 0, 45, 90, 135, 180, 225, 270, 315]:
        point = origin + z_mm / scale * axis
        p = pose[:, :3] @ point + pose[:, 3]
        u = round(cam.params[0] * p[0] / p[2] + cam.params[2])
        v = round(cam.params[1] * p[1] / p[2] + cam.params[3])
        if 0 <= u < photo.shape[1] and 0 <= v < photo.shape[0]:
            cv2.circle(photo, (u, v), 8, (0, 255, 0), -1)
            cv2.putText(photo, str(z_mm), (u+12, v+5), cv2.FONT_HERSHEY_SIMPLEX,
                        .75, (0, 255, 0), 2, cv2.LINE_AA)
    cv2.imwrite(str(OUT / ('axis_' + im.name)), photo)
