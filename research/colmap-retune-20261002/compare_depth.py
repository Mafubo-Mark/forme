"""Evaluate the same two hand-checked frame-36 body patches in depth maps.

Coordinates refer to the 1350x2400 undistorted image. Validity means COLMAP
returned a positive depth; it does not establish physical accuracy.
"""
from __future__ import annotations

import json
import argparse
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
SCALE = 141.22180552601463
BOXES = {"black_socket_mid": (950, 350, 1200, 850), "white_tube": (980, 1200, 1180, 1400)}


def depth(path: Path):
    # COLMAP uses an ampersand-separated ASCII header followed by float32 data.
    with path.open("rb") as f:
        parts = []
        while len(parts) < 3:
            chars = bytearray()
            while (c := f.read(1)) != b"&":
                if not c:
                    raise ValueError(f"truncated header: {path}")
                chars += c
            parts.append(int(chars))
        w, h, channels = parts
        arr = np.fromfile(f, dtype=np.float32)
    if arr.size != w * h * channels:
        raise ValueError(f"bad array size: {path}")
    return arr.reshape((h, w, channels))[:, :, 0]


def crop(a, box):
    x0, y0, x1, y1 = box
    h, w = a.shape
    x0, x1 = round(x0*w/1350), round(x1*w/1350)
    y0, y1 = round(y0*h/2400), round(y1*h/2400)
    return a[y0:y1, x0:x1]


parser = argparse.ArgumentParser()
parser.add_argument("--kind", choices=("geometric", "photometric"), default="geometric")
args = parser.parse_args()
base_path = ROOT / f"reconstruction/dense/stereo/depth_maps/frame_00036.jpg.{args.kind}.bin"
new_path = OUT / f"patch-relaxed/stereo/depth_maps/frame_00036.jpg.{args.kind}.bin"
base = depth(base_path)
result = {"kind": args.kind, "baseline_shape": list(base.shape), "patches": {}}
if new_path.exists():
    new = depth(new_path)
    result["new_shape"] = list(new.shape)
else:
    new = None
for name, box in BOXES.items():
    b = crop(base, box)
    item = {"original_image_box": list(box), "baseline_valid_fraction": round(float(np.mean(b > 0)), 5)}
    if new is not None:
        n = crop(new, box)
        both = (b > 0) & (n > 0)
        new_only = (b <= 0) & (n > 0)
        item.update({
            "retuned_valid_fraction": round(float(np.mean(n > 0)), 5),
            "new_only_fraction": round(float(np.mean(new_only)), 5),
            "lost_fraction": round(float(np.mean((b > 0) & (n <= 0))), 5),
            "shared_depth_difference_mm_median": round(float(np.median(np.abs(b[both]-n[both])*SCALE)), 3) if both.any() else None,
            "shared_depth_difference_mm_p90": round(float(np.percentile(np.abs(b[both]-n[both])*SCALE, 90)), 3) if both.any() else None,
        })
    result["patches"][name] = item
(OUT / f"depth-comparison-{args.kind}.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
