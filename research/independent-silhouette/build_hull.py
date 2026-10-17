"""Diagnostic visual hull from photo-native Vision masks and COLMAP poses.

No dense point cloud, 3DGS, or point-cloud-derived masks are read. The existing
sparse-axis JSON only bounds the search volume; it does not supply a surface.
"""
from pathlib import Path
import json

import cv2
import numpy as np
import pycolmap
import trimesh
from scipy import ndimage as ndi
from skimage.measure import marching_cubes

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
OUT = ROOT / 'independent-silhouette'
MASKS = OUT / 'masks'
scale = json.loads((ROOT / 'analysis/scale-calibration.json').read_text())['mm_per_colmap_unit']
roi = json.loads((ROOT / 'analysis/isolation-config.json').read_text())
rec = pycolmap.Reconstruction(str(ROOT / 'reconstruction/dense/sparse'))

origin = np.array(roi['origin_colmap'], dtype=np.float64)
axis = np.array(roi['axis_colmap'], dtype=np.float64)
axis /= np.linalg.norm(axis)
reference = np.array([0., 0., 1.])
if abs(np.dot(axis, reference)) > .95:
    reference = np.array([1., 0., 0.])
x_axis = np.cross(axis, reference)
x_axis /= np.linalg.norm(x_axis)
y_axis = np.cross(axis, x_axis)

# Search bounds are deliberately wider than the object. This 3 mm grid is a
# diagnostic of observable envelope, not a fabrication tolerance.
step = 3.0
xy = np.arange(-108., 108.1, step, dtype=np.float32)
z = np.arange(-0.48 * scale, 2.25 * scale + .1, step, dtype=np.float32)
zz, yy, xx = np.meshgrid(z, xy, xy, indexing='ij')
local = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).astype(np.float32)
world = (origin[None, :] + local[:, 0:1] / scale * x_axis[None, :]
         + local[:, 1:2] / scale * y_axis[None, :]
         + local[:, 2:3] / scale * axis[None, :]).astype(np.float32)

images = sorted([rec.images[i] for i in rec.reg_image_ids()], key=lambda im: im.name)
holdout = {im.name for i, im in enumerate(images) if i % 7 == 3}
seen = np.zeros(len(world), dtype=np.uint16)
inside = np.zeros(len(world), dtype=np.uint16)

def project(points, im, cam, divisor=2):
    pose = np.asarray(im.cam_from_world().matrix(), dtype=np.float32)
    p = points @ pose[:, :3].T + pose[:, 3]
    fx, fy, cx, cy = np.asarray(cam.params[:4], dtype=np.float32) / divisor
    with np.errstate(divide='ignore', invalid='ignore'):
        u = np.rint(fx * p[:, 0] / p[:, 2] + cx).astype(np.int32)
        v = np.rint(fy * p[:, 1] / p[:, 2] + cy).astype(np.int32)
    return u, v, p[:, 2]

kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
for k, im in enumerate(images, 1):
    if im.name in holdout:
        continue
    cam = rec.cameras[im.camera_id]
    mask = cv2.imread(str(MASKS / f'{Path(im.name).stem}.png'), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise FileNotFoundError(im.name)
    mask = cv2.resize(mask, (cam.width // 2, cam.height // 2), interpolation=cv2.INTER_AREA)
    mask = cv2.dilate((mask >= 127).astype(np.uint8), kernel)
    u, v, depth = project(world, im, cam)
    valid = (depth > 0) & (u >= 0) & (u < mask.shape[1]) & (v >= 0) & (v < mask.shape[0])
    ids = np.flatnonzero(valid)
    seen[ids] += 1
    inside[ids] += mask[v[ids], u[ids]]
    if k % 15 == 0:
        print(f'processed {k}/{len(images)}', flush=True)

ratio = np.divide(inside, seen, out=np.zeros(len(world), np.float32), where=seen > 0)
support = ((seen >= 35) & (ratio >= .90)).reshape(len(z), len(xy), len(xy))
raw_count = int(support.sum())
labels, n_components = ndi.label(support)
if n_components:
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    support = labels == sizes.argmax()
largest_count = int(support.sum())

if largest_count:
    verts, faces, _, _ = marching_cubes(np.pad(support.astype(np.uint8), 1), .5,
                                        spacing=(step, step, step))
    verts -= step
    vertices = np.column_stack([xy[0] + verts[:, 2], xy[0] + verts[:, 1], z[0] + verts[:, 0]])
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.export(OUT / 'photo_native_hull_preview.ply')
else:
    vertices = np.zeros((0, 3))

survivors = world[np.flatnonzero(support.ravel())]
holdout_scores = []
for im in images:
    if im.name not in holdout:
        continue
    cam = rec.cameras[im.camera_id]
    ref = cv2.imread(str(MASKS / f'{Path(im.name).stem}.png'), cv2.IMREAD_GRAYSCALE)
    ref = cv2.resize(ref, (cam.width // 2, cam.height // 2), interpolation=cv2.INTER_AREA) >= 127
    prediction = np.zeros(ref.shape, np.uint8)
    if len(survivors):
        u, v, depth = project(survivors, im, cam)
        valid = (depth > 0) & (u >= 0) & (u < ref.shape[1]) & (v >= 0) & (v < ref.shape[0])
        prediction[v[valid], u[valid]] = 1
        prediction = cv2.dilate(prediction, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    # A local box avoids scoring the shoe and floor card, which are outside
    # this upper-leg ROI. It is only a diagnostic and can miss an absent tip.
    hits = np.argwhere(prediction)
    if len(hits):
        y0, x0 = np.maximum(hits.min(axis=0) - 20, 0)
        y1, x1 = np.minimum(hits.max(axis=0) + 21, ref.shape)
        local_ref = ref[y0:y1, x0:x1]
        local_pred = prediction[y0:y1, x0:x1] > 0
        inter = int(np.count_nonzero(local_ref & local_pred))
        union = int(np.count_nonzero(local_ref | local_pred))
        iou = inter / union if union else 0.
    else:
        iou = 0.
    photo = cv2.imread(str(ROOT / 'reconstruction/dense/images' / im.name))
    photo = cv2.resize(photo, (ref.shape[1], ref.shape[0]))
    edge_ref = cv2.morphologyEx(ref.astype(np.uint8), cv2.MORPH_GRADIENT, kernel)
    edge_pred = cv2.morphologyEx(prediction, cv2.MORPH_GRADIENT, kernel)
    dist_to_ref = cv2.distanceTransform(1 - edge_ref, cv2.DIST_L2, 3)
    edge_distances = dist_to_ref[edge_pred > 0]
    holdout_scores.append({
        'image': im.name,
        'local_iou_including_any_paper_or_shoe': round(iou, 3),
        'predicted_pixels_on_foreground_fraction': round(float(np.count_nonzero(prediction & ref)) / max(1, np.count_nonzero(prediction)), 3),
        'predicted_edge_to_photo_mask_median_px_half_res': round(float(np.median(edge_distances)), 2) if len(edge_distances) else None,
        'predicted_edge_to_photo_mask_p90_px_half_res': round(float(np.percentile(edge_distances, 90)), 2) if len(edge_distances) else None,
    })
    photo[edge_ref > 0] = (0, 0, 255)
    photo[edge_pred > 0] = (0, 255, 0)
    cv2.imwrite(str(OUT / f'holdout_{Path(im.name).stem}.jpg'), photo)

np.savez_compressed(OUT / 'photo_native_hull_volume.npz', support=support,
                    x_mm=xy, y_mm=xy, z_mm=z, origin_colmap=origin,
                    axes_colmap=np.stack([x_axis, y_axis, axis]))
report = {
    'status': 'diagnostic_only_not_print_approved',
    'input_masks': 'macOS Vision from original undistorted photos; no point cloud or 3DGS mask input',
    'camera_poses': 'COLMAP sparse registration',
    'sparse_axis_use': 'search-volume bounds only; not shape evidence',
    'scale_mm_per_colmap_unit': scale,
    'grid_step_mm': step,
    'train_images': len(images) - len(holdout),
    'holdout_images': len(holdout),
    'raw_supported_voxels': raw_count,
    'connected_components': int(n_components),
    'largest_component_voxels': largest_count,
    'heldout_local_iou': holdout_scores,
    'limitations': [
        'Foreground masks include shoe and sometimes calibration paper; spatial ROI and local validation limit but do not prove their influence is absent.',
        'The 3 mm voxel grid cannot establish millimeter fit.',
        'Open top, bolt recesses, and hidden concavities are not determined by exterior silhouettes.',
        'Held-out image silhouette agreement is not physical metrology.'
    ]
}
(OUT / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({k: report[k] for k in ('raw_supported_voxels', 'connected_components', 'largest_component_voxels', 'heldout_local_iou')}, indent=2))
