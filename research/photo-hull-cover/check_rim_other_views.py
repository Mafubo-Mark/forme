"""Project two-overhead-view upper rim inference into other COLMAP views."""
import json
from pathlib import Path
import cv2
import numpy as np
import pycolmap

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
curve=np.load(HERE/'rim_two_view_fit.npz')
frame=np.array([cfg['x_in_input_coordinates'],cfg['front_in_input_coordinates'],cfg['axis_in_input_coordinates']]).T
shift=cfg['trim_low_input_coordinate']*cfg['input_to_mm_scale']+cfg['cover_start_mm']
green=np.load(HERE/'green_profiles.npz')
c=green['center_xy_mm'][-1]
t=curve['theta'];r=curve['radius_mm'];z=curve['z_mm']
local=np.column_stack((c[0]+r*np.cos(t),c[1]+r*np.sin(t),z+shift))
world=np.array(cfg['origin_in_input_coordinates'])+local@frame.T/cfg['input_to_mm_scale']
rec=pycolmap.Reconstruction(str(ROOT/'reconstruction/dense/sparse'))
for no in [4,32,40,75,82]:
    name=f'frame_{no:05d}.jpg'
    im=next(v for v in rec.images.values() if v.name==name)
    pose=np.asarray(im.cam_from_world().matrix())
    p=world@pose[:,:3].T+pose[:,3]
    fx,fy,cx,cy=rec.cameras[im.camera_id].params[:4]
    uv=np.column_stack((fx*p[:,0]/p[:,2]+cx,fy*p[:,1]/p[:,2]+cy))
    photo=cv2.imread(str(ROOT/'reconstruction/dense/images'/name))
    # Draw dots, since hidden points would make an unvalidated solid line.
    for pt in uv:
        cv2.circle(photo,tuple(np.rint(pt).astype(int)),2,(255,0,0),-1)
    cv2.putText(photo,'BLUE: upper rim fit from frames 75 and 82',(30,65),cv2.FONT_HERSHEY_SIMPLEX,.9,(255,0,0),2,cv2.LINE_AA)
    cv2.imwrite(str(HERE/f'upper_rim_two_view_crossview_{no:05d}.jpg'),photo)
