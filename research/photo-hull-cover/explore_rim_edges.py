"""Diagnose whether registered photos can localize a free upper-rim curve."""
import json
from pathlib import Path

import cv2
import numpy as np
import pycolmap
from PIL import Image, ImageDraw

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
green=np.load(HERE/'green_profiles.npz')
angles=np.linspace(np.deg2rad(122),np.deg2rad(418),241)
radius=np.interp(np.mod(angles,2*np.pi),
                 np.r_[green['angles_rad'],2*np.pi],
                 np.r_[green['object_radius_mm'][-1],green['object_radius_mm'][-1,0]])
center=green['center_xy_mm'][-1]
zs=np.arange(278,365,2,dtype=float)
xy=np.column_stack((center[0]+radius*np.cos(angles),center[1]+radius*np.sin(angles)))
points=np.tile(xy[None,:,:],(len(zs),1,1))
points=np.concatenate((points,np.broadcast_to(zs[:,None,None],(len(zs),len(angles),1))),axis=2).reshape(-1,3)
frame=np.asarray([cfg['x_in_input_coordinates'],cfg['front_in_input_coordinates'],
                  cfg['axis_in_input_coordinates']]).T
shift=cfg['trim_low_input_coordinate']*cfg['input_to_mm_scale']+cfg['cover_start_mm']
points[:,2]+=shift
world=np.asarray(cfg['origin_in_input_coordinates'])+points@frame.T/cfg['input_to_mm_scale']
rec=pycolmap.Reconstruction(str(ROOT/'reconstruction/dense/sparse'))
settings={40:(810,1350,250,660),75:(65,690,500,1300)}
all_cost=[]
for number,roi in settings.items():
    name=f'frame_{number:05d}.jpg'
    im=next(x for x in rec.images.values() if x.name==name)
    cam=rec.cameras[im.camera_id]
    photo=cv2.imread(str(ROOT/'reconstruction/dense/images'/name))
    gray=cv2.cvtColor(photo,cv2.COLOR_BGR2GRAY)
    blur=cv2.GaussianBlur(gray,(0,0),2.5)
    edge=cv2.Canny(blur,40,100)
    x0,x1,y0,y1=roi
    limited=np.zeros_like(edge)
    limited[y0:y1,x0:x1]=edge[y0:y1,x0:x1]
    dist=cv2.distanceTransform(255-limited,cv2.DIST_L2,3)
    pose=np.asarray(im.cam_from_world().matrix())
    p=world@pose[:,:3].T+pose[:,3]
    fx,fy,cx,cy=cam.params[:4]
    uv=np.column_stack((fx*p[:,0]/p[:,2]+cx,fy*p[:,1]/p[:,2]+cy))
    u=np.rint(uv[:,0]).astype(int);v=np.rint(uv[:,1]).astype(int)
    valid=(p[:,2]>0)&(u>=x0)&(u<x1)&(v>=y0)&(v<y1)
    cost=np.full(len(u),30.,dtype=float)
    cost[valid]=np.minimum(dist[v[valid],u[valid]],30)
    cost=cost.reshape(len(zs),len(angles))
    all_cost.append(cost)
    cv2.imwrite(str(HERE/f'rim_edges_{number}.png'),limited)
    view=np.uint8(255*(1-np.clip(cost,0,30)/30))
    cv2.imwrite(str(HERE/f'rim_edge_cost_{number}.png'),cv2.resize(view,(964,704),interpolation=cv2.INTER_NEAREST))
np.savez_compressed(HERE/'rim_edge_costs.npz',zs=zs,angles=angles,cost40=all_cost[0],cost75=all_cost[1])
combined=np.mean(all_cost,axis=0)
view=np.uint8(255*(1-np.clip(combined,0,30)/30))
cv2.imwrite(str(HERE/'rim_edge_cost_combined.png'),cv2.resize(view,(964,704),interpolation=cv2.INTER_NEAREST))
