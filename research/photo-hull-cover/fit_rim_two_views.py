"""Diagnostic two-view fit of dark cavity boundary, with axial radius prior."""
import json
from pathlib import Path
import cv2
import numpy as np
import pycolmap
from scipy.ndimage import gaussian_filter1d

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
green=np.load(HERE/'green_profiles.npz')
theta=green['angles_rad'][::2]
r0=green['object_radius_mm'][-1,::2]
c=green['center_xy_mm'][-1]
axes=np.array([cfg['x_in_input_coordinates'],cfg['front_in_input_coordinates'],cfg['axis_in_input_coordinates']]).T
shift=cfg['trim_low_input_coordinate']*cfg['input_to_mm_scale']+cfg['cover_start_mm']
origin=np.array(cfg['origin_in_input_coordinates'])
scale=cfg['input_to_mm_scale']
rec=pycolmap.Reconstruction(str(ROOT/'reconstruction/dense/sparse'))

def contour_distance(no,rect):
    photo=cv2.imread(str(ROOT/f'reconstruction/dense/images/frame_{no:05d}.jpg'))
    gray=cv2.cvtColor(photo,cv2.COLOR_BGR2GRAY)
    roi=np.zeros(gray.shape,np.uint8)
    cv2.rectangle(roi,rect[:2],rect[2:],255,-1)
    dark=((gray<100)&(roi>0)).astype(np.uint8)
    n,lab,st,_=cv2.connectedComponentsWithStats(dark)
    mask=(lab==np.argmax(st[1:,4])+1).astype(np.uint8)
    cs,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    edge=np.zeros_like(mask)
    cv2.drawContours(edge,[max(cs,key=cv2.contourArea)],-1,1,2)
    dist=cv2.distanceTransform(1-edge,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
    im=next(v for v in rec.images.values() if v.name==f'frame_{no:05d}.jpg')
    return photo,dist,np.asarray(im.cam_from_world().matrix()),rec.cameras[im.camera_id].params[:4]

views={82:contour_distance(82,(390,690,930,1240)),75:contour_distance(75,(70,480,590,1280))}
rvals=np.arange(37,71,1.0)
zvals=np.arange(250,381,1.0)
rr=rvals[None,:,None]+np.zeros((len(theta),1,len(zvals)))
zz=zvals[None,None,:]+np.zeros((len(theta),len(rvals),1))
tt=theta[:,None,None]+np.zeros_like(rr)
local=np.stack((c[0]+rr*np.cos(tt),c[1]+rr*np.sin(tt),zz+shift),axis=-1).reshape(-1,3)
world=origin+local@axes.T/scale
cost=np.zeros(len(world))
for no,(photo,dist,pose,params) in views.items():
    pc=world@pose[:,:3].T+pose[:,3]
    fx,fy,cx,cy=params
    px=np.rint(fx*pc[:,0]/pc[:,2]+cx).astype(int)
    py=np.rint(fy*pc[:,1]/pc[:,2]+cy).astype(int)
    valid=(px>=0)&(px<photo.shape[1])&(py>=0)&(py<photo.shape[0])&(pc[:,2]>0)
    d=np.full(len(world),500.0)
    d[valid]=dist[py[valid],px[valid]]
    cost+=np.minimum(d,100)**2
cost=cost.reshape(len(theta),len(rvals),len(zvals))
cost+=(0.8*(rr-r0[:,None,None]))**2
flat=np.argmin(cost.reshape(len(theta),-1),axis=1)
ri,zi=np.unravel_index(flat,(len(rvals),len(zvals)))
rfit=rvals[ri];zfit=zvals[zi]
rsmooth=gaussian_filter1d(rfit,2,mode='wrap')
zsmooth=gaussian_filter1d(zfit,2,mode='wrap')
np.savez_compressed(HERE/'rim_two_view_fit.npz',theta=theta,radius_mm=rsmooth,z_mm=zsmooth,raw_radius_mm=rfit,raw_z_mm=zfit)
for no,(photo,dist,pose,params) in views.items():
    local=np.column_stack((c[0]+rsmooth*np.cos(theta),c[1]+rsmooth*np.sin(theta),zsmooth+shift))
    world=origin+local@axes.T/scale
    pc=world@pose[:,:3].T+pose[:,3]
    fx,fy,cx,cy=params
    uv=np.column_stack((fx*pc[:,0]/pc[:,2]+cx,fy*pc[:,1]/pc[:,2]+cy))
    for p in uv:
        cv2.circle(photo,tuple(np.rint(p).astype(int)),2,(255,0,0),-1)
    cv2.imwrite(str(HERE/f'rim_two_view_overlay_{no:05d}.jpg'),photo)
    pix=np.rint(uv).astype(int)
    print(no,'median distance',np.median(dist[pix[:,1],pix[:,0]]),'p90',np.quantile(dist[pix[:,1],pix[:,0]],.9))
print('z range',zfit.min(),zfit.max(),'r range',rfit.min(),rfit.max(),'max z jump',np.max(abs(np.diff(zfit))))
