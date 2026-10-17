"""Compare the previous full-shell profiles with independent photo silhouettes."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import ConvexHull

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'pointcloud-contour-prototype'))
import build_partial_shell as pc

cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
scan=pc.load_points(cfg)
data=np.load(ROOT/'independent-silhouette/photo_native_hull_volume.npz')
ids=np.argwhere(data['support'])
old_local=np.column_stack((data['x_mm'][ids[:,2]],data['y_mm'][ids[:,1]],data['z_mm'][ids[:,0]]))
old_origin=data['origin_colmap']
old_frame=data['axes_colmap']
world=old_origin+old_local@old_frame/cfg['input_to_mm_scale']
new_origin=np.array(cfg['origin_in_input_coordinates'])
new_frame=np.array([cfg['x_in_input_coordinates'],cfg['front_in_input_coordinates'],
                    cfg['axis_in_input_coordinates']]).T
hull=(world-new_origin)@new_frame*cfg['input_to_mm_scale']
hull[:,2]-=cfg['trim_low_input_coordinate']*cfg['input_to_mm_scale']+cfg['cover_start_mm']
prof=np.load(ROOT/'pointcloud-full-cover-prototype/profile_data.npz')
zs=prof['zs']; angles=prof['angles']; inner=prof['inner']; center=prof['center']
levels=[100,150,200,250,300]
im=Image.new('RGB',(1200,600*len(levels)),'white')
draw=ImageDraw.Draw(im)
report=[]
angles=np.asarray(prof['angles'])
for row,z in enumerate(levels):
    a=scan[np.abs(scan[:,2]-z)<4,:2]
    b=hull[np.abs(hull[:,2]-z)<4,:2]
    ox,oy=600,600*row+310
    cvt=lambda p:(ox+p[0]*3.1,oy-p[1]*3.1)
    draw.text((20,600*row+15),f'z={z} mm  grey: COLMAP points  green: independent photo visual hull  orange: previous shell inner',fill='black')
    if len(a)>3000:
        a=a[np.random.default_rng(z).choice(len(a),3000,replace=False)]
    for p in a:
        x,y=cvt(p);draw.ellipse((x-1,y-1,x+1,y+1),fill='#999999')
    comparison={}
    if len(b)>3:
        ch=ConvexHull(b)
        poly=[cvt(p) for p in b[ch.vertices]]
        draw.line(poly+poly[:1],fill='#15855f',width=4)
        # Rasterize the convex hull at 0.5 mm/pixel to compare radial envelopes.
        n=round(2*pc.GRID_HALF_MM/pc.GRID_MM)+1
        pix=np.rint((b[ch.vertices]+np.array([pc.GRID_HALF_MM,-pc.GRID_HALF_MM]))
                     *np.array([1,-1])/pc.GRID_MM).astype(np.int32)
        mask=np.zeros((n,n),np.uint8)
        cv2.fillConvexPoly(mask,pix,255)
        green=pc.radial_profile(pc.largest_contour(mask),center,angles)
        old_radius=inner[np.argmin(np.abs(zs-z))]
        gap=old_radius-green
        comparison={'previous_shell_minus_photo_hull_radius_median_mm':round(float(np.median(gap)),2),
                    'previous_shell_minus_photo_hull_radius_p90_mm':round(float(np.quantile(gap,.9)),2),
                    'previous_shell_minus_photo_hull_radius_min_mm':round(float(gap.min()),2)}
    i=np.argmin(np.abs(zs-z))
    contour=[cvt(center+radius*np.array([np.cos(t),np.sin(t)]))
             for t,radius in zip(angles,inner[i])]
    draw.line(contour,fill='#d77a18',width=3)
    report.append({'z_mm':z,'scan_points_in_8mm_band':len(a),'photo_hull_voxels_in_8mm_band':len(b),**comparison})
im.save(ROOT/'pointcloud-full-cover-prototype/independent_hull_comparison.png')
(ROOT/'pointcloud-full-cover-prototype/independent_hull_comparison.json').write_text(json.dumps(report,indent=2)+'\n')
