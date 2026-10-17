"""Prepare test4 COLMAP views for Pixal3D's posed multiview input.

Creates centered virtual pinhole views by rotating the original undistorted
cameras about their centers. The transform metadata follows Pixal3D's Blender
camera convention. This remains a prototype: subject masks and the lower cutoff
must be reviewed before interpreting a generated mesh as fitted geometry.
"""

from pathlib import Path
import json
import math

import cv2
import numpy as np
import pycolmap


ROOT = Path('/Volumes/extra/workspace1/projects/test4')
OUT = ROOT / 'pixal3d-trial'
VIEWS = OUT / 'views'
VIEWS.mkdir(parents=True, exist_ok=True)

RECON = pycolmap.Reconstruction(str(ROOT / 'reconstruction/dense/sparse'))
ROI = json.loads((ROOT / 'analysis/isolation-config.json').read_text())
SCALE_MM = json.loads((ROOT / 'analysis/scale-calibration.json').read_text())['mm_per_colmap_unit']
ORIGIN = np.asarray(ROI['origin_colmap'], dtype=float)
AXIS_DOWN = np.asarray(ROI['axis_colmap'], dtype=float)
AXIS_DOWN /= np.linalg.norm(AXIS_DOWN)

# Rough cover extent, referenced to the independently reviewed axis overlay.
# The white-tube end is near 335 mm, just above the cloth and shoe.
Z_TOP = -0.55
Z_BOTTOM = 2.37
TARGET = ORIGIN + AXIS_DOWN * ((Z_TOP + Z_BOTTOM) / 2)

# First image has the highest camera elevation of the four. This minimizes the
# tilt when the first view is converted to Pixal3D's canonical front camera.
SELECTED = ['frame_00053.jpg', 'frame_00008.jpg',
            'frame_00021.jpg', 'frame_00037.jpg']
HOLDOUT = ['frame_00014.jpg', 'frame_00029.jpg',
           'frame_00045.jpg', 'frame_00060.jpg']
SIDE = 1024
HEIGHT_FRACTION = 0.81
MODEL_HEIGHT = 0.90
WORLD_SCALE = MODEL_HEIGHT / (Z_BOTTOM - Z_TOP)


def unit(v):
    return v / np.linalg.norm(v)


def project_axis(virtual_rotation, center, focal, z):
    p = ORIGIN + AXIS_DOWN * z
    camera = virtual_rotation.T @ (p - center)
    return np.array([SIDE / 2 + focal * camera[0] / -camera[2],
                     SIDE / 2 - focal * camera[1] / -camera[2]])


def make_virtual_view(image_name):
    im = next(x for x in RECON.images.values() if x.name == image_name)
    camera = RECON.cameras[im.camera_id]
    if camera.model.name != 'PINHOLE':
        raise RuntimeError(f'{image_name}: expected undistorted PINHOLE camera')
    fx, fy, cx, cy = map(float, camera.params[:4])
    center = np.asarray(im.projection_center(), dtype=float)
    back = unit(center - TARGET)
    up_hint = -AXIS_DOWN
    right = unit(np.cross(up_hint, back))
    up = unit(np.cross(back, right))
    virtual_rotation = np.column_stack([right, up, back])

    # Set virtual focal length so the axial subject occupies about 81% of each
    # square view; actual cameras and perspective remain encoded in the metadata.
    top_unit = project_axis(virtual_rotation, center, 1.0, Z_TOP)
    bottom_unit = project_axis(virtual_rotation, center, 1.0, Z_BOTTOM)
    focal = HEIGHT_FRACTION * SIDE / abs(top_unit[1] - bottom_unit[1])
    fov = 2 * math.atan(SIDE / (2 * focal))

    # A pure camera rotation allows exact pinhole reprojection without depth.
    original_bgr = cv2.imread(str(ROOT / 'reconstruction/dense/images' / image_name))
    original_mask = cv2.imread(str(ROOT / 'independent-silhouette/masks' /
                                    f'{Path(image_name).stem}.png'), cv2.IMREAD_GRAYSCALE)
    if original_bgr is None or original_mask is None:
        raise FileNotFoundError(image_name)
    if original_bgr.shape[:2] != original_mask.shape[:2]:
        raise ValueError(f'{image_name}: image/mask size mismatch')

    yy, xx = np.mgrid[:SIDE, :SIDE].astype(np.float32)
    rays_virtual = np.stack([(xx - SIDE / 2) / focal,
                             -(yy - SIDE / 2) / focal,
                             -np.ones_like(xx)], axis=-1)
    world_rays = rays_virtual @ virtual_rotation.T
    r_world_to_cv = np.asarray(im.cam_from_world().matrix(), dtype=float)[:, :3]
    original_rays = world_rays @ r_world_to_cv.T
    depth = original_rays[..., 2]
    map_x = (fx * original_rays[..., 0] / depth + cx).astype(np.float32)
    map_y = (fy * original_rays[..., 1] / depth + cy).astype(np.float32)
    map_x[depth <= 0] = -1
    map_y[depth <= 0] = -1
    rgb = cv2.remap(original_bgr, map_x, map_y, cv2.INTER_AREA,
                    borderMode=cv2.BORDER_CONSTANT)
    alpha = cv2.remap(original_mask, map_x, map_y, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT)

    # The Vision mask also includes the shoe and sometimes the calibration paper.
    # Keep a generous strip around the axis, ending above the ankle cloth.
    top = project_axis(virtual_rotation, center, focal, Z_TOP)
    bottom = project_axis(virtual_rotation, center, focal, Z_BOTTOM)
    mid = project_axis(virtual_rotation, center, focal, (Z_TOP + Z_BOTTOM) / 2)
    axis_x_at_y = top[0] + (bottom[0] - top[0]) * (yy - top[1]) / max(1., bottom[1] - top[1])
    lower_section = yy > min(top[1], bottom[1]) + 0.67 * abs(bottom[1] - top[1])
    radius_world = np.where(lower_section, 0.30, 0.72)
    radial_px = focal * radius_world / max(0.5, np.linalg.norm(center - TARGET) - 1.0)
    keep = ((yy >= min(top[1], bottom[1]) - 12)
            & (yy <= max(top[1], bottom[1]) + 8)
            & (np.abs(xx - axis_x_at_y) <= radial_px))
    alpha = np.where(keep, alpha, 0).astype(np.uint8)
    alpha = np.where(alpha >= 128, 255, 0).astype(np.uint8)
    # Frame 53's shoe enters the broad foreground component at the very bottom.
    # Its left edge jumps from x≈454 to x≈395 after row 815; the tube remains
    # x≈454–605 there. Limit that local spill without touching the upper rim.
    if image_name == 'frame_00053.jpg':
        alpha[(yy >= 815) & (xx < 450)] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(alpha, 8)
    if count > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        alpha = np.where(labels == largest, 255, 0).astype(np.uint8)

    rgba = np.dstack([rgb, alpha])
    return {
        'name': image_name, 'center': center, 'rotation': virtual_rotation,
        'focal': focal, 'fov': fov, 'rgba': rgba,
        'top': top, 'bottom': bottom, 'mid': mid,
        'alpha_pixels': int(np.count_nonzero(alpha)),
        'mask_bbox': cv2.boundingRect(alpha),
    }


views = [make_virtual_view(name) for name in SELECTED]
# Rotation into the canonical front-camera frame used by the Pixal3D trainer.
front = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)
to_model = front @ views[0]['rotation'].T
frames = []
contact_tiles = []
for index, view in enumerate(views):
    filename = f'view{index:02d}_{Path(view["name"]).stem}.png'
    path = VIEWS / filename
    cv2.imwrite(str(path), view['rgba'], [cv2.IMWRITE_PNG_COMPRESSION, 4])
    pose = np.eye(4)
    pose[:3, :3] = to_model @ view['rotation']
    pose[:3, 3] = WORLD_SCALE * to_model @ (view['center'] - TARGET)
    frames.append({
        'file_path': filename,
        'name': Path(view['name']).stem,
        'camera_angle_x': view['fov'],
        'transform_matrix': pose.round(9).tolist(),
    })
    bg = np.full((SIDE, SIDE, 3), 235, np.uint8)
    a = view['rgba'][..., 3:4].astype(float) / 255
    bg = (bg * (1-a) + view['rgba'][..., :3] * a).astype(np.uint8)
    cv2.putText(bg, view['name'], (16, 42), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (20, 20, 20), 2, cv2.LINE_AA)
    contact_tiles.append(cv2.resize(bg, (420, 420), interpolation=cv2.INTER_AREA))

(VIEWS / 'transforms.json').write_text(json.dumps({
    'mesh_scale': 1.0,
    'frames': frames,
}, indent=2))
cv2.imwrite(str(OUT / 'input-contact-sheet.jpg'),
            np.hstack(contact_tiles), [cv2.IMWRITE_JPEG_QUALITY, 93])

# Separate photos were never shown to Pixal3D. They allow a more honest
# silhouette check than measuring agreement only on the four condition views.
holdout_dir = OUT / 'holdout-views'
holdout_dir.mkdir(parents=True, exist_ok=True)
holdout_frames = []
holdout_tiles = []
for index, name in enumerate(HOLDOUT):
    view = make_virtual_view(name)
    filename = f'holdout{index:02d}_{Path(name).stem}.png'
    cv2.imwrite(str(holdout_dir / filename), view['rgba'],
                [cv2.IMWRITE_PNG_COMPRESSION, 4])
    pose = np.eye(4)
    pose[:3, :3] = to_model @ view['rotation']
    pose[:3, 3] = WORLD_SCALE * to_model @ (view['center'] - TARGET)
    holdout_frames.append({
        'file_path': filename, 'name': Path(name).stem,
        'camera_angle_x': view['fov'],
        'transform_matrix': pose.round(9).tolist(),
    })
    bg = np.full((SIDE, SIDE, 3), 235, np.uint8)
    a = view['rgba'][..., 3:4].astype(float) / 255
    bg = (bg * (1-a) + view['rgba'][..., :3] * a).astype(np.uint8)
    cv2.putText(bg, name, (16, 42), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (20, 20, 20), 2, cv2.LINE_AA)
    holdout_tiles.append(cv2.resize(bg, (420, 420), interpolation=cv2.INTER_AREA))
(holdout_dir / 'transforms.json').write_text(json.dumps({
    'mesh_scale': 1.0, 'frames': holdout_frames,
}, indent=2))
cv2.imwrite(str(OUT / 'holdout-contact-sheet.jpg'),
            np.hstack(holdout_tiles), [cv2.IMWRITE_JPEG_QUALITY, 93])
(OUT / 'preparation-report.json').write_text(json.dumps({
    'source': 'test4 undistorted photos, independent macOS Vision masks, COLMAP cameras',
    'selected_frames': SELECTED,
    'holdout_frames': HOLDOUT,
    'scale_mm_per_colmap_unit': SCALE_MM,
    'normalized_world_scale_per_colmap_unit': WORLD_SCALE,
    'mm_per_pixal3d_unit_if_model_preserved_camera_scale': SCALE_MM / WORLD_SCALE,
    'estimated_covered_height_mm': (Z_BOTTOM - Z_TOP) * SCALE_MM,
    'view_stats': [{k: v for k, v in view.items() if k in
                    ('name', 'focal', 'fov', 'alpha_pixels', 'mask_bbox')}
                   for view in views],
    'warning': 'The Vision masks and lower cutoff are approximate; GLB needs photo reprojection and physical verification before cover design.'
}, indent=2))
print(OUT)
for v in views:
    print(v['name'], 'fov_deg=', round(math.degrees(v['fov']), 1),
          'alpha_pixels=', v['alpha_pixels'], 'bbox=', v['mask_bbox'])
