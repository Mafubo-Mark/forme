"""Project the 3DGS-driven cover back into calibrated test4 camera views."""
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pycolmap
import trimesh
from PIL import Image, ImageDraw, ImageFont

ROOT=Path('/Volumes/extra/workspace1/projects/test4')
CAD=Path(os.environ.get('COVER_CAD_DIR', str(ROOT/'gs-experiment/cad-v4')))
sec=json.loads(Path(os.environ.get('COVER_SECTIONS_FILE', str(ROOT/'gs-experiment/cad-v4/sections.json'))).read_text())
mesh=trimesh.load_mesh(CAD/os.environ.get('COVER_MESH_FILE', 'fitted_c_cover.stl'))
v=np.asarray(mesh.vertices)
sc=sec['input_to_mm_scale']
o=np.asarray(sec['origin_in_input_coordinates'])
x=np.asarray(sec['x_in_input_coordinates'])
y=np.asarray(sec['front_in_input_coordinates'])
z=np.asarray(sec['axis_in_input_coordinates'])
lo=sec['trim_low_input_coordinate']
start=sec['cover_start_mm']
world=(o+v[:,0:1]/sc*x+v[:,1:2]/sc*y+
       ((v[:,2:3]+start)/sc+lo)*z)
rec=pycolmap.Reconstruction(str(ROOT/'reconstruction/dense/sparse'))
fontpath='/System/Library/Fonts/Hiragino Sans GB.ttc'
font=ImageFont.truetype(fontpath,32)
for name in ('frame_00011.jpg','frame_00036.jpg','frame_00051.jpg'):
    im=rec.find_image_with_name(name)
    cam=rec.cameras[im.camera_id]
    photo=cv2.cvtColor(cv2.imread(str(ROOT/'reconstruction/dense/images'/name)),cv2.COLOR_BGR2RGB)
    h,w=photo.shape[:2]
    pose=np.asarray(im.cam_from_world().matrix())
    pts=world@pose[:,:3].T+pose[:,3]
    fx,fy,cx,cy=cam.params
    uv=np.column_stack((fx*pts[:,0]/pts[:,2]+cx,fy*pts[:,1]/pts[:,2]+cy))
    faces=np.asarray(mesh.faces)
    a,b,c=pts[faces[:,0]],pts[faces[:,1]],pts[faces[:,2]]
    facing=np.sum(np.cross(b-a,c-a)*(-a),axis=1)>0
    mask=np.zeros((h,w),np.uint8)
    for f in faces[facing]:
        if np.all(pts[f,2]>0):
            cv2.fillConvexPoly(mask,np.round(uv[f]).astype(np.int32),255)
    overlay=photo.copy()
    overlay[mask>0]=(overlay[mask>0]*.52+np.array([4,195,215])*.48).astype(np.uint8)
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay,contours,-1,(0,255,255),4,cv2.LINE_AA)
    out=Image.new('RGB',(2*w,h+80),(245,248,250))
    out.paste(Image.fromarray(photo),(0,80));out.paste(Image.fromarray(overlay),(w,80))
    d=ImageDraw.Draw(out)
    d.text((18,20),f'{name}  实拍',font=font,fill=(22,46,58))
    d.text((w+18,20),'预览模型投影（形状核对，非生产件）',font=font,fill=(22,46,58))
    path=CAD/(name.replace('.jpg','-projection.jpg'))
    out.save(path,quality=92)
    ys,xs=np.where(mask>0)
    print(name,'projected bounds x/y',
          (int(xs.min()),int(xs.max()),int(ys.min()),int(ys.max())) if len(xs) else None)
