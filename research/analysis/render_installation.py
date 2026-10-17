#!/usr/bin/env python3
"""Project the test4 CAD cover into a registered COLMAP video frame."""
import json
from pathlib import Path

import cv2
import numpy as np
import pycolmap
import trimesh
from PIL import Image, ImageDraw, ImageFont

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
FRAME = 'frame_00036.jpg'
sections = json.loads((ROOT / 'cad-review/sections.json').read_text())
rec = pycolmap.Reconstruction(str(ROOT / 'reconstruction/dense/sparse'))
im = rec.find_image_with_name(FRAME)
cam = rec.cameras[im.camera_id]
rgb = cv2.cvtColor(cv2.imread(str(ROOT / 'reconstruction/dense/images' / FRAME)), cv2.COLOR_BGR2RGB)
h, w = rgb.shape[:2]
mesh = trimesh.load_mesh(ROOT / 'cad-review/fitted_c_cover.stl')

# Invert the exact world-to-CAD transform used for the cover loft.
scale = sections['input_to_mm_scale']
origin = np.asarray(sections['origin_in_input_coordinates'])
xaxis = np.asarray(sections['x_in_input_coordinates'])
yaxis = np.asarray(sections['front_in_input_coordinates'])
zaxis = np.asarray(sections['axis_in_input_coordinates'])
low = sections['trim_low_input_coordinate']
start = sections['cover_start_mm']
v = np.asarray(mesh.vertices)
world = (origin[None, :] + v[:, 0:1] / scale * xaxis[None, :]
         + v[:, 1:2] / scale * yaxis[None, :]
         + ((v[:, 2:3] + start) / scale + low) * zaxis[None, :])
pose = np.asarray(im.cam_from_world().matrix())
vc = world @ pose[:, :3].T + pose[:, 3]
fx, fy, cx, cy = cam.params
proj = np.column_stack((fx * vc[:, 0] / vc[:, 2] + cx,
                        fy * vc[:, 1] / vc[:, 2] + cy))
print('Projected CAD bbox:', np.min(proj, axis=0), np.max(proj, axis=0),
      'depth:', np.min(vc[:,2]), np.max(vc[:,2]))

# Only surfaces facing the camera contribute to the visible installed shell.
f = np.asarray(mesh.faces)
p0, p1, p2 = vc[f[:, 0]], vc[f[:, 1]], vc[f[:, 2]]
normal = np.cross(p1-p0, p2-p0)
front = np.sum(normal * (-p0), axis=1) > 0
mask = np.zeros((h, w), np.uint8)
for tri in f[front]:
    if np.all(vc[tri, 2] > 0):
        cv2.fillConvexPoly(mask, np.round(proj[tri]).astype(np.int32), 255)
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3,3),np.uint8))

# Save the actual CAD projection separately for fit review. It is visibly wider
# than the photographed shell and must not be presented as an installed fit.
diagnostic = rgb.copy()
diagnostic[mask > 0] = (diagnostic[mask > 0] * .48 +
                        np.array([9,190,205]) * .52).astype(np.uint8)
cv2.imwrite(str(ROOT / 'analysis/cad-projection-mismatch.png'),
            cv2.cvtColor(diagnostic, cv2.COLOR_RGB2BGR))

# Intent drawing: trace the visible black housing and white tube. These screen
# coordinates are an approximate installation area, not measured CAD geometry.
mask[:] = 0
target_outline = np.array([
    [898, 265], [922, 320], [980, 368], [1051, 370], [1124, 334],
    [1198, 281], [1278, 235], [1259, 402], [1224, 618],
    [1196, 829], [1180, 936], [1180, 1325], [1171, 1400],
    [954, 1400], [942, 1325], [933, 947], [939, 827],
    [927, 645], [911, 461]
], np.int32)
cv2.fillPoly(mask, [target_outline], 255)
# Indicate the bolt clearance at the existing hardware position.
cv2.ellipse(mask, (1142, 1195), (43, 46), 0, 0, 360, 0, -1)

overlay = rgb.copy()
teal = np.array([9, 190, 205], dtype=np.float32)
a = (mask.astype(np.float32) / 255.0 * .52)[:, :, None]
overlay = np.clip(overlay * (1-a) + teal[None,None,:] * a, 0, 255).astype(np.uint8)
contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
cv2.drawContours(overlay, contours, -1, (0, 245, 245), 4, cv2.LINE_AA)

# Crop the same region from the real frame and from the CAD overlay.
crop = (590, 0, 1340, 1500)
left = Image.fromarray(rgb).crop(crop)
right = Image.fromarray(overlay).crop(crop)
cw, ch = left.size
pad, gap, header, footer = 56, 38, 158, 190
out = Image.new('RGB', (2*cw + 2*pad + gap, ch+header+footer), (245,248,250))
d = ImageDraw.Draw(out)
fontpath = '/System/Library/Fonts/Hiragino Sans GB.ttc'
title = ImageFont.truetype(fontpath, 46)
sub = ImageFont.truetype(fontpath, 30)
small = ImageFont.truetype(fontpath, 24)
d.text((pad, 34), 'test4 保护套安装位置示意', fill=(24,46,58), font=title)
d.text((pad, 102), '计划覆盖范围示意 · 基于 test4 实拍，不代表 CAD 已贴合', fill=(82,104,116), font=sub)
lx, rx, py = pad, pad+cw+gap, header
out.paste(left, (lx,py)); out.paste(right,(rx,py))
d.rectangle((lx,py,lx+cw,py+ch), outline=(205,217,223), width=2)
d.rectangle((rx,py,rx+cw,py+ch), outline=(0,168,185), width=3)
for x,label in [(lx,'原始实拍'),(rx,'青色：计划覆盖位置')]:
    d.rounded_rectangle((x+16,py+16,x+404,py+71),radius=16,fill=(16,47,58))
    d.text((x+34,py+23),label,font=sub,fill='white')

# Call out design intent, independent of the current oversized CAD projection.
for px,py0,label,dy in [(898,265,'上缘绕开开口',-38),
                        (954,1400,'下缘止于鞋口上方',-20),
                        (1142,1195,'螺栓避让',-30)]:
    xx=rx+px-crop[0]; yy=py+py0-crop[1]
    if 0 <= xx < out.width and 0 <= yy < out.height:
        d.ellipse((xx-8, yy-8, xx+8, yy+8),fill=(255,191,51),outline='white',width=2)
        tx=max(rx+10,min(xx-90,rx+cw-190)); ty=max(py+100,min(yy+dy,py+ch-40))
        d.line((xx,yy,tx+8,ty+22),fill=(255,191,51),width=4)
        d.text((tx,ty),label,font=small,fill=(255,191,51),stroke_width=2,stroke_fill=(16,47,58))

d.text((pad,header+ch+28), '结构意向：覆盖黑壳与白色筒身；背侧 C 形开口；螺栓处避让。',font=sub,fill=(24,46,58))
d.text((pad,header+ch+83), '当前 CAD 投影明显偏宽，需重新拟合后再进行打印试装。',
       font=small,fill=(179,62,44))
dest = ROOT / 'analysis/installation-schematic.png'
out.save(dest, optimize=True)
print(dest)
