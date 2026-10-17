"""Project the old height-rule rim onto registered photos for visual rejection/review."""
import json
from pathlib import Path

import cv2
import numpy as np
import pycolmap

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
green=np.load(HERE/'green_profiles.npz')
old=np.load(ROOT/'pointcloud-full-cover-prototype/profile_data.npz')
angles=old['angles']; rim=old['rim']
green_angles=green['angles_rad']; radius=green['object_radius_mm'][-1]
center=green['center_xy_mm'][-1]
angle_mod=np.mod(angles,2*np.pi)
radius_full=np.r_[radius,radius[0]]
angle_full=np.r_[green_angles,2*np.pi]
rr=np.interp(angle_mod,angle_full,radius_full)
local=np.column_stack((center[0]+rr*np.cos(angles),center[1]+rr*np.sin(angles),rim))
frame=np.array([cfg['x_in_input_coordinates'],cfg['front_in_input_coordinates'],
                cfg['axis_in_input_coordinates']]).T
shift=cfg['trim_low_input_coordinate']*cfg['input_to_mm_scale']+cfg['cover_start_mm']
local[:,2]+=shift
world=np.array(cfg['origin_in_input_coordinates'])+local@frame.T/cfg['input_to_mm_scale']
rec=pycolmap.Reconstruction(str(ROOT/'reconstruction/dense/sparse'))
report=[]
for frame_no in (4,32,40,75):
    name=f'frame_{frame_no:05d}.jpg'
    im=next((x for x in rec.images.values() if x.name==name),None)
    if im is None:
        raise ValueError(f'Not registered: {name}')
    cam=rec.cameras[im.camera_id]
    pose=np.asarray(im.cam_from_world().matrix())
    p=world@pose[:,:3].T+pose[:,3]
    fx,fy,cx,cy=cam.params[:4]
    uv=np.column_stack((fx*p[:,0]/p[:,2]+cx,fy*p[:,1]/p[:,2]+cy))
    photo=cv2.imread(str(ROOT/'reconstruction/dense/images'/name))
    valid=p[:,2]>0
    for i in range(len(uv)-1):
        if valid[i] and valid[i+1]:
            a=tuple(np.rint(uv[i]).astype(int));b=tuple(np.rint(uv[i+1]).astype(int))
            cv2.line(photo,a,b,(0,220,255),3,cv2.LINE_AA)
    cv2.putText(photo,'YELLOW: previous scan-height rule; NOT a traced physical rim',
                (30,65),cv2.FONT_HERSHEY_SIMPLEX,1,(0,220,255),2,cv2.LINE_AA)
    output=HERE/f'rim_rule_overlay_{name}'
    cv2.imwrite(str(output),photo,[cv2.IMWRITE_JPEG_QUALITY,92])
    report.append({'photo':name,'projected_points':int(valid.sum()),'output':str(output)})
(HERE/'rim_rule_projection_report.json').write_text(json.dumps(report,indent=2)+'\n')
