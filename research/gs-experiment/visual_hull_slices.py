"""Carve calibrated cross-section occupancy from all registered alpha views."""
import json
from pathlib import Path

import cv2
import numpy as np
import pycolmap
from PIL import Image, ImageDraw

ROOT=Path('/Volumes/extra/workspace1/projects/test4')
BASE=ROOT/'gs-experiment'
sec=json.loads((ROOT/'cad-review/sections.json').read_text())
rec=pycolmap.Reconstruction(str(ROOT/'reconstruction/dense/sparse'))
scale=sec['input_to_mm_scale']
o=np.asarray(sec['origin_in_input_coordinates'])
x=np.asarray(sec['x_in_input_coordinates'])
y=np.asarray(sec['front_in_input_coordinates'])
z=np.asarray(sec['axis_in_input_coordinates'])
lo=sec['trim_low_input_coordinate']
start=sec['cover_start_mm']

grid=np.arange(-125,126,3,dtype=np.float32)
xx,yy=np.meshgrid(grid,grid,indexing='xy')
heights=np.arange(20,341,30,dtype=np.float32)
coords=np.column_stack((np.tile(xx.ravel(),len(heights)),
                        np.tile(yy.ravel(),len(heights)),
                        np.repeat(heights,xx.size)))
world=(o+coords[:,0:1]/scale*x+coords[:,1:2]/scale*y+
       ((coords[:,2:3]+start)/scale+lo)*z)
inside=np.zeros(len(world),np.uint16)
seen=np.zeros(len(world),np.uint16)
for idx in rec.reg_image_ids():
    im=rec.images[idx]
    cam=rec.cameras[im.camera_id]
    alpha=cv2.imread(str(BASE/'dataset-alpha/images'/f'{Path(im.name).stem}.png'),
                     cv2.IMREAD_UNCHANGED)
    if alpha is None:
        raise FileNotFoundError(im.name)
    alpha=cv2.resize(alpha[:,:,3],(cam.width//2,cam.height//2),interpolation=cv2.INTER_AREA)
    pose=np.asarray(im.cam_from_world().matrix())
    p=world@pose[:,:3].T+pose[:,3]
    fx,fy,cx,cy=np.asarray(cam.params[:4])/2
    u=np.rint(fx*p[:,0]/p[:,2]+cx).astype(np.int32)
    v=np.rint(fy*p[:,1]/p[:,2]+cy).astype(np.int32)
    valid=(p[:,2]>0)&(u>=0)&(u<alpha.shape[1])&(v>=0)&(v<alpha.shape[0])
    vi=np.flatnonzero(valid)
    seen[vi]+=1
    inside[vi]+=(alpha[v[vi],u[vi]]>=127)
mask=(seen>=40)&(inside>=np.ceil(seen*0.93))
volume=mask.reshape(len(heights),len(grid),len(grid))
np.savez_compressed(BASE/'visual-hull-slices.npz',occupancy=volume,
                    grid_x_mm=grid,grid_y_mm=grid,heights_mm=heights,
                    source_views=len(rec.reg_image_ids()))

canvas=Image.new('RGB',(4*300,3*340),(245,247,249))
draw=ImageDraw.Draw(canvas)
for i,h in enumerate(heights):
    plane=volume[i].astype(np.uint8)*255
    n,labels,stats,_=cv2.connectedComponentsWithStats(plane,8)
    if n>1:
        plane=(labels==(1+np.argmax(stats[1:,cv2.CC_STAT_AREA]))).astype(np.uint8)*255
    ys,xs=np.where(plane>0)
    if len(xs):
        print('z',h,'width x/y mm',
              round(float(np.ptp(grid[xs])),1),round(float(np.ptp(grid[ys])),1),
              'area cells',len(xs),flush=True)
    tile=cv2.resize(plane,(280,280),interpolation=cv2.INTER_NEAREST)
    tile_rgb=np.zeros((280,280,3),np.uint8)
    tile_rgb[:]=[239,244,246]
    tile_rgb[tile>0]=[13,154,171]
    x0,y0=(i%4)*300,(i//4)*340
    canvas.paste(Image.fromarray(tile_rgb),(x0+10,y0+38))
    draw.text((x0+12,y0+12),f'z={h:.0f} mm',fill=(34,58,68))
canvas.save(BASE/'visual-hull-slices.png')
