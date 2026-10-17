"""Render comparable axial sections of CGAL envelope, old shell, scan and AI."""
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image,ImageDraw

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
model=trimesh.load(HERE/'union_a8_o7.off',process=False)
ref=np.load(HERE/'union_eval_reference.npz')
scan=ref['scan'];ai=ref['model']
p=np.load(ROOT/'photo-hull-cover/body_shell_profiles.npz')
zs=p['z_mm'];angles=p['angles_rad'];center=p['centers_xy_mm'];inner=p['inner_radius_mm']
image=Image.new('RGB',(1500,1500),'white')
d=ImageDraw.Draw(image)
for panel,z in enumerate([100,130,200,260]):
    ox=panel%2*750;oy=panel//2*750
    def xy(pt):return (int(ox+375+pt[0]*4),int(oy+385-pt[1]*4))
    d.rectangle((ox+35,oy+55,ox+715,oy+725),outline='#bbbbbb')
    ss=scan[abs(scan[:,2]-z)<3,:2]
    aa=ai[abs(ai[:,2]-z)<3,:2]
    for q in ss:d.point(xy(q),fill='#999999')
    for q in aa:d.point(xy(q),fill='#cb88a8')
    jj=np.argmin(abs(zs-z));c=center[jj]
    old=np.column_stack((c[0]+inner[jj]*np.cos(angles),c[1]+inner[jj]*np.sin(angles)))
    d.line([xy(q) for q in old],fill='#037caa',width=3)
    section=model.section(plane_origin=[0,0,z],plane_normal=[0,0,1])
    loops=[]
    if section is not None:
        for curve in section.discrete:
            q=curve[:,:2]
            area=abs(np.sum(q[:,0]*np.roll(q[:,1],-1)-q[:,1]*np.roll(q[:,0],-1))/2)
            loops.append((area,q))
    if loops:
        outer=max(loops,key=lambda x:x[0])[1]
        d.line([xy(q) for q in outer],fill='#299550',width=4,joint='curve')
    d.text((ox+48,oy+65),f'z={z} mm | gray scan | pink Hunyuan | blue old inner | green CGAL outer',fill='#222222')
image.save(HERE/'sections_a8_o7.png')
