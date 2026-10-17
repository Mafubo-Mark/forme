"""Trace visible dark-cavity rim in registered overhead photograph (diagnostic)."""
import json
from pathlib import Path
import cv2
import numpy as np
import pycolmap
from scipy.ndimage import distance_transform_edt, gaussian_filter1d

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
green=np.load(HERE/'green_profiles.npz')
frame=np.array([cfg['x_in_input_coordinates'],cfg['front_in_input_coordinates'],cfg['axis_in_input_coordinates']]).T
shift=cfg['trim_low_input_coordinate']*cfg['input_to_mm_scale']+cfg['cover_start_mm']
origin=np.array(cfg['origin_in_input_coordinates'])
scale=cfg['input_to_mm_scale']
rec=pycolmap.Reconstruction(str(ROOT/'reconstruction/dense/sparse'))
im=next(v for v in rec.images.values() if v.name=='frame_00082.jpg')
cam=rec.cameras[im.camera_id]
pose=np.asarray(im.cam_from_world().matrix())
fx,fy,cx,cy=cam.params[:4]
photo=cv2.imread(str(ROOT/'reconstruction/dense/images/frame_00082.jpg'))
gray=cv2.cvtColor(photo,cv2.COLOR_BGR2GRAY)
roi=np.zeros(gray.shape,np.uint8)
cv2.rectangle(roi,(390,690),(930,1240),255,-1)
dark=((gray<100)&(roi>0)).astype(np.uint8)
n,lab,stats,_=cv2.connectedComponentsWithStats(dark)
index=np.argmax(stats[1:,4])+1
mask=(lab==index).astype(np.uint8)
contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
contour=max(contours,key=cv2.contourArea)
edge=np.zeros(mask.shape,np.uint8)
cv2.drawContours(edge,[contour],-1,1,1)
dist=distance_transform_edt(1-edge)

def project(theta,z,r):
    c=green['center_xy_mm'][-1]
    local=np.column_stack((c[0]+r*np.cos(theta),c[1]+r*np.sin(theta),z+np.zeros_like(theta)+shift))
    world=origin+local@frame.T/scale
    pc=world@pose[:,:3].T+pose[:,3]
    return np.column_stack((fx*pc[:,0]/pc[:,2]+cx,fy*pc[:,1]/pc[:,2]+cy))

theta=green['angles_rad'][::2]
radius=green['object_radius_mm'][-1,::2]
zs=np.arange(250,391,0.5)
scores=np.empty((len(theta),len(zs)))
uvs=np.empty((len(theta),len(zs),2))
for j,z in enumerate(zs):
    uv=project(theta,np.full_like(theta,z),radius)
    uvs[:,j]=uv
    pix=np.rint(uv).astype(int)
    valid=(pix[:,0]>=0)&(pix[:,0]<photo.shape[1])&(pix[:,1]>=0)&(pix[:,1]<photo.shape[0])
    scores[:,j]=1000
    scores[valid,j]=dist[pix[valid,1],pix[valid,0]]

raw_index=np.argmin(scores,axis=1)
raw_z=zs[raw_index]
smooth=gaussian_filter1d(raw_z,3,mode='wrap')
for tag,zvals,color in [('raw',raw_z,(0,255,255)),('smooth',smooth,(255,0,0))]:
    uv=project(theta,zvals,radius)
    for pt in uv:
        cv2.circle(photo,tuple(np.rint(pt).astype(int)),2,color,-1)
    np.savez_compressed(HERE/f'rim_trace_{tag}.npz',theta=theta,z_mm=zvals,radius_mm=radius,uv_px=uv,edge_distance_px=dist[np.clip(np.rint(uv[:,1]).astype(int),0,dist.shape[0]-1),np.clip(np.rint(uv[:,0]).astype(int),0,dist.shape[1]-1)])
cv2.drawContours(photo,[contour],-1,(0,0,255),2)
cv2.putText(photo,'red: dark cavity boundary; yellow: raw fit; blue: smoothed',(30,65),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,0),4)
cv2.putText(photo,'red: dark cavity boundary; yellow: raw fit; blue: smoothed',(30,65),cv2.FONT_HERSHEY_SIMPLEX,.8,(255,255,255),2)
cv2.imwrite(str(HERE/'rim_trace_frame_00082.jpg'),photo)
print('raw z range',np.min(raw_z),np.max(raw_z),'median distance',np.median(np.min(scores,axis=1)),'p90',np.quantile(np.min(scores,axis=1),.9))
