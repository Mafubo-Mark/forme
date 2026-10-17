"""Suggest two printed circular ruler targets; the operator must confirm them.

This is deliberately a proposal, not a scale calibration. The sample target has
two high contrast concentric rings in the lower portion of the capture.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def suggest(path: Path) -> dict:
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError("FRAME_UNREADABLE")
    height, width = gray.shape
    start = int(height * 0.58)
    blurred = cv2.GaussianBlur(gray[start:], (7, 7), 1.8)
    circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, dp=1.2,
                               minDist=max(35, width * 0.035), param1=110,
                               param2=52, minRadius=max(12, int(width * 0.012)),
                               maxRadius=max(65, int(width * 0.05)))
    items = []
    if circles is not None:
        for x, y, radius in circles[0]:
            x, y, radius = float(x), float(y + start), float(radius)
            if x - radius < 0 or x + radius >= width or y - radius < 0 or y + radius >= height:
                continue
            # Refine the ring's imperfect Hough center to its isolated dark dot.
            reach = int(radius)
            x0, y0 = int(x) - reach, int(y) - reach
            patch = gray[y0:y0 + 2 * reach + 1, x0:x0 + 2 * reach + 1]
            if patch.shape != (2 * reach + 1, 2 * reach + 1):
                continue
            _, dark = cv2.threshold(patch, 90, 255, cv2.THRESH_BINARY_INV)
            count, _, stats, centers = cv2.connectedComponentsWithStats(dark)
            dots = []
            for index in range(1, count):
                area = int(stats[index, cv2.CC_STAT_AREA])
                cx, cy = centers[index]
                distance = float(np.hypot(cx + x0 - x, cy + y0 - y))
                if 12 <= area <= 0.12 * np.pi * radius * radius and distance < 0.5 * radius:
                    dots.append((distance, float(cx + x0), float(cy + y0), area))
            if not dots:
                continue
            _, center_x, center_y, area = min(dots)
            score = float(area / (np.pi * radius * radius))
            items.append({"point": [round(center_x, 2), round(center_y, 2)], "radiusPx": round(radius, 2),
                          "patternScore": round(score, 2)})
    items.sort(key=lambda item: item["patternScore"], reverse=True)
    # Never force a pair if only one circle was found.
    pair = sorted(items[:2], key=lambda item: item["point"][0]) if len(items) >= 2 else []
    return {"status": "SUGGESTION_REQUIRES_OPERATOR_CONFIRMATION", "frame": path.name,
            "imageSize": [width, height], "suggestedPair": pair, "candidates": items[:8]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    print(json.dumps(suggest(args.image), ensure_ascii=False))
