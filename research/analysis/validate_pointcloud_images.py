"""Reproject the isolated COLMAP cloud into registered source video frames.

This is an image consistency check, not an independent physical measurement.
"""
from pathlib import Path
import json

import cv2
import numpy as np
import pycolmap
from plyfile import PlyData


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "pointcloud-image-validation"
OUT.mkdir(exist_ok=True)
MODEL = ROOT / "reconstruction" / "dense" / "sparse"
FRAMES = ROOT / "reconstruction" / "dense" / "images"
PLY = ROOT / "analysis" / "isolated-prosthesis.ply"
FRAME_NUMBERS = [9, 17, 25, 33, 41, 49, 57, 68, 73, 81, 88]

v = PlyData.read(str(PLY))["vertex"].data
xyz = np.stack([v[a] for a in "xyz"], axis=1).astype(np.float64)
rgb = np.stack([v[a] for a in ("red", "green", "blue")], axis=1)
reconstruction = pycolmap.Reconstruction(str(MODEL))
images_by_name = {i.name: i for i in reconstruction.images.values()}
results = []
tiles = []
for number in FRAME_NUMBERS:
    name = f"frame_{number:05d}.jpg"
    if name not in images_by_name or not (FRAMES / name).exists():
        continue
    image = images_by_name[name]
    camera = reconstruction.cameras[image.camera_id]
    pose = image.cam_from_world()
    cam = xyz @ pose.rotation.matrix().T + pose.translation
    valid = cam[:, 2] > 0
    fx, fy, cx, cy = camera.params
    uv = np.column_stack([fx * cam[:, 0] / cam[:, 2] + cx,
                          fy * cam[:, 1] / cam[:, 2] + cy])
    valid &= (uv[:, 0] >= 0) & (uv[:, 0] < camera.width)
    valid &= (uv[:, 1] >= 0) & (uv[:, 1] < camera.height)
    raw = cv2.imread(str(FRAMES / name))
    if raw.shape[1] != camera.width or raw.shape[0] != camera.height:
        raise RuntimeError(f"Camera/image dimensions differ for {name}")
    uv_int = np.rint(uv[valid]).astype(np.int32)
    uv_int[:, 0] = np.clip(uv_int[:, 0], 0, camera.width - 1)
    uv_int[:, 1] = np.clip(uv_int[:, 1], 0, camera.height - 1)
    colors = rgb[valid]
    # The dark shell is the relevant surface for cover fitting. White support,
    # yellow tape and shoe are excluded from the silhouette metric.
    dark = (colors.max(axis=1) < 115) & (colors.mean(axis=1) < 85)
    pts = uv_int[dark]
    projected = np.zeros(raw.shape[:2], np.uint8)
    projected[pts[:, 1], pts[:, 0]] = 255
    projected = cv2.morphologyEx(projected, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    projected = cv2.dilate(projected, np.ones((7, 7), np.uint8))
    # Color-only source mask inside a broad independent box. The box only
    # selects the object region; the source pixels determine the silhouette.
    x0, y0 = np.percentile(pts, 1, axis=0).astype(int)
    x1, y1 = np.percentile(pts, 99, axis=0).astype(int)
    margin = 55
    x0, y0 = max(0, x0-margin), max(0, y0-margin)
    x1, y1 = min(camera.width, x1+margin), min(camera.height, y1+margin)
    region = raw[y0:y1, x0:x1]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    # Dark, low value carbon fiber; connected component at projected center
    # excludes dark background objects in the broad region.
    mask = np.zeros(raw.shape[:2], np.uint8)
    candidate = ((hsv[:, :, 2] < 115) & (hsv[:, :, 1] < 145)).astype(np.uint8) * 255
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE,
                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate)
    if count > 1:
        # Select component with most projected points, not its shape.
        local = pts - [x0, y0]
        inside = ((local[:, 0] >= 0) & (local[:, 0] < candidate.shape[1]) &
                  (local[:, 1] >= 0) & (local[:, 1] < candidate.shape[0]))
        counts = np.bincount(labels[local[inside, 1], local[inside, 0]], minlength=count)
        counts[0] = 0
        chosen = int(np.argmax(counts))
        mask[y0:y1, x0:x1] = (labels == chosen).astype(np.uint8)*255
    # Score how often projected surface lands on visually dark source pixels.
    source_hsv = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
    dark_pixel = ((source_hsv[:, :, 2] < 115) & (source_hsv[:, :, 1] < 145))
    dark_hit_fraction = float(np.mean(dark_pixel[pts[:, 1], pts[:, 0]]))
    mask_area = np.count_nonzero(mask)
    projected_area = np.count_nonzero(projected)
    intersection = np.count_nonzero((mask > 0) & (projected > 0))
    union = np.count_nonzero((mask > 0) | (projected > 0))
    iou = float(intersection/union) if union else 0.0
    recall = float(intersection/mask_area) if mask_area else 0.0
    precision = float(intersection/projected_area) if projected_area else 0.0
    # Orange=source-only; cyan=cloud-only; green=agreement.
    compare = raw.copy()
    a = (mask > 0) & (projected == 0)
    b = (projected > 0) & (mask == 0)
    c = (projected > 0) & (mask > 0)
    tint = compare.copy(); tint[a] = (0, 135, 255); tint[b] = (255, 220, 0); tint[c] = (0, 220, 0)
    compare = cv2.addWeighted(compare, 0.5, tint, 0.5, 0)
    cv2.rectangle(compare, (x0, y0), (x1, y1), (255, 255, 255), 2)
    cv2.putText(compare, f"frame {number} / IoU {iou:.2f} / hit {dark_hit_fraction:.2f}",
                (35, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 4)
    cv2.imwrite(str(OUT / f"frame_{number:05d}_comparison.jpg"), compare,
                [cv2.IMWRITE_JPEG_QUALITY, 90])
    small = cv2.resize(compare, (405, 720), interpolation=cv2.INTER_AREA)
    tiles.append(small)
    results.append({"frame": name, "cloudDarkPointsProjected": int(len(pts)),
                    "darkPixelHitFraction": dark_hit_fraction,
                    "silhouetteIoU": iou, "silhouetteRecall": recall,
                    "silhouettePrecision": precision,
                    "colorMaskAreaPixels": int(mask_area),
                    "projectedAreaPixels": int(projected_area)})

if tiles:
    while len(tiles) % 4:
        tiles.append(np.full_like(tiles[0], 255))
    rows = [np.hstack(tiles[i:i+4]) for i in range(0, len(tiles), 4)]
    cv2.imwrite(str(OUT / "contact_sheet.jpg"), np.vstack(rows),
                [cv2.IMWRITE_JPEG_QUALITY, 90])
report = {"method": "Registered COLMAP source-frame reprojection of isolated dense cloud; dark-source color mask is approximate and view-dependent.",
          "frames": results,
          "medianDarkPixelHitFraction": float(np.median([r["darkPixelHitFraction"] for r in results])),
          "medianSilhouetteIoU": float(np.median([r["silhouetteIoU"] for r in results])),
          "uprightFrameCount": sum(int(r["frame"][6:11]) <= 57 for r in results),
          "uprightMedianSilhouetteIoU": float(np.median([r["silhouetteIoU"] for r in results if int(r["frame"][6:11]) <= 57])),
          "assessment": "VISIBLE_EXTERIOR_IMAGE_CONSISTENT_TOP_INTERIOR_AND_ENDS_INCOMPLETE",
          "observations": ["The visible outer black-shell silhouette is broadly consistent in seven upright views.",
                           "The overhead view shows a central region of the open cavity without projected cloud support.",
                           "Lower and upper axial sections have incomplete angular coverage in the separate density audit."],
          "physicalSurfaceFitVerified": False,
          "limitations": ["Frames are the same source video used for reconstruction, so this is a consistency check, not independent shape accuracy.",
                          "Dark color segmentation and projected point dilation are approximate; inspect overlays before using silhouette scores.",
                          "Occluded and unobserved interior/rear surfaces cannot be verified from visible silhouettes."]}
(OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"frames": len(results), "medianHit": report["medianDarkPixelHitFraction"], "medianIoU": report["medianSilhouetteIoU"]}))
