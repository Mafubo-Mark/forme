"""Compare photo-hull cover inner wall to the user-supplied Hunyuan v2 mesh.

Both are brought into the corrected prosthesis-axis millimetre frame.  The
radial audit evaluates overlap with the shell's inner wall; it is not a
physical fit test and cannot validate fastening or insertion path.
"""
import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
iso=json.loads((ROOT/'analysis/isolation-config.json').read_text())
mm=json.loads((ROOT/'analysis/scale-calibration.json').read_text())['mm_per_colmap_unit']
cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
profiles=np.load(HERE/'body_shell_profiles.npz')
zs=profiles['z_mm'];angles=profiles['angles_rad'];centers=profiles['centers_xy_mm'];inner=profiles['inner_radius_mm'];active=profiles['active_cells']
shell=trimesh.load(HERE/'photo_hull_body_shell.stl',process=False)
model=trimesh.load(ROOT/'hunyuan31-v2-comparison/hunyuan31-v2-aligned-mm.stl',process=False)
samples,_=trimesh.sample.sample_surface(model,350000,seed=20260929)
axis=np.asarray(iso['axis_colmap'],float);axis/=np.linalg.norm(axis)
xaxis=np.cross(axis,[1.,0.,0.]);xaxis/=np.linalg.norm(xaxis)
yaxis=np.cross(axis,xaxis)
basis=np.stack([xaxis,yaxis,-axis],axis=1)
world=np.asarray(iso['origin_colmap'])+(samples/mm)@basis.T
frame=np.array([cfg['x_in_input_coordinates'],cfg['front_in_input_coordinates'],cfg['axis_in_input_coordinates']]).T
local=(world-np.array(cfg['origin_in_input_coordinates']))@frame*cfg['input_to_mm_scale']
local[:,2]-=cfg['trim_low_input_coordinate']*cfg['input_to_mm_scale']+cfg['cover_start_mm']
local_all=local.copy()

# Orthographic coverage overview using the same transformed geometry.
overview=Image.new('RGB',(1600,900),'white');od=ImageDraw.Draw(overview)
view_model=local_all[(local_all[:,2]>=0)&(local_all[:,2]<=380)&
    (np.linalg.norm(local_all[:,:2],axis=1)<100)][::4]
view_shell=np.asarray(shell.vertices)[::3]
for vi,axis_index in enumerate([0,1]):
    ox=vi*800
    od.rectangle((ox+60,80,ox+750,825),outline='#cccccc')
    def pixel(p):return (int(ox+405+p[axis_index]*3.0),int(800-p[2]*1.8))
    for point in view_model:od.point(pixel(point),fill='#d4a0bb')
    for point in view_shell:od.point(pixel(point),fill='#087f9f')
    od.text((ox+70,35),('X-Z side' if vi==0 else 'Y-Z front')+' | pink Hunyuan v2 | blue current cover',fill='black')
    y275=int(800-275*1.8)
    od.line((ox+60,y275,ox+750,y275),fill='#666666',width=1)
    od.text((ox+65,y275-20),'cover ends at 275 mm',fill='#444444')
overview.save(HERE/'hunyuan_v2_cover_overview.png')

# Limit the upper prosthesis and cylindrical stem.  The Hunyuan file also
# contains a shoe and hallucinated structures beyond the shell's z interval.
body=(local[:,2]>=zs[0])&(local[:,2]<=zs[-1])
local=local[body]
j=np.clip(np.searchsorted(zs,local[:,2])-1,0,len(zs)-2)
blend=(local[:,2]-zs[j])/(zs[j+1]-zs[j])
center=centers[j]*(1-blend[:,None])+centers[j+1]*blend[:,None]
rel=local[:,:2]-center
rad=np.linalg.norm(rel,axis=1)
angle=np.mod(np.arctan2(rel[:,1],rel[:,0])-angles[0],2*np.pi)+angles[0]
sector=(angle>=angles[0])&(angle<=angles[-1])&(rad<100)
cell_i=np.clip(np.searchsorted(angles,angle)-1,0,len(angles)-2)
keep=sector&active[j,cell_i]
local,j,blend,rel,rad,angle=(a[keep] for a in (local,j,blend,rel,rad,angle))
i=np.clip(np.searchsorted(angles,angle)-1,0,len(angles)-2)
beta=(angle-angles[i])/(angles[i+1]-angles[i])
r=(inner[j,i]*(1-blend)*(1-beta)+inner[j+1,i]*blend*(1-beta)
   +inner[j,i+1]*(1-blend)*beta+inner[j+1,i+1]*blend*beta)
gap=r-rad

zones={}
for lo,hi in [(20,90),(90,150),(150,230),(230,275)]:
    use=(local[:,2]>=lo)&(local[:,2]<hi)
    d=gap[use]
    zones[f'{lo}-{hi}mm']={'samples':int(len(d)),'penetrating_samples':int((d<0).sum()),
        'penetrating_fraction':round(float((d<0).mean()),5) if len(d) else None,
        'gap_min_mm':round(float(d.min()),2) if len(d) else None,
        'gap_p01_mm':round(float(np.quantile(d,.01)),2) if len(d) else None,
        'gap_median_mm':round(float(np.median(d)),2) if len(d) else None}

# Stable local maximum violations in 5 mm x 5 degree bins.
height_bins=np.arange(20,280,5)
angle_bins=np.arange(angles[0],angles[-1]+np.deg2rad(5),np.deg2rad(5))
zi=np.clip(np.digitize(local[:,2],height_bins)-1,0,len(height_bins)-2)
ai=np.clip(np.digitize(angle,angle_bins)-1,0,len(angle_bins)-2)
bin_count=np.zeros((len(height_bins)-1,len(angle_bins)-1),int)
bin_min=np.full(bin_count.shape,np.inf)
np.add.at(bin_count,(zi,ai),1)
np.minimum.at(bin_min,(zi,ai),gap)
strong=(bin_count>=20)
bad=strong&(bin_min<0)

canvas=Image.new('RGB',(1400,1400),'white')
d=ImageDraw.Draw(canvas)
for idx,z in enumerate([50,125,200,260]):
    ox=(idx%2)*700;oy=(idx//2)*700
    d.rectangle((ox+30,oy+50,ox+670,oy+690),outline='#bbbbbb',width=1)
    def xy(pt):return (int(ox+350+pt[0]*3.5),int(oy+370-pt[1]*3.5))
    use=np.abs(local[:,2]-z)<=3
    xy=local[use,:2]
    if len(xy)>5000: xy=xy[::max(1,len(xy)//5000)]
    for pt in xy:d.point((int(ox+350+pt[0]*3.5),int(oy+370-pt[1]*3.5)),fill='#be8dab')
    jj=np.argmin(abs(zs-z))
    cc=centers[jj]
    contour=np.column_stack((cc[0]+inner[jj]*np.cos(angles),cc[1]+inner[jj]*np.sin(angles)))
    d.line([(int(ox+350+p[0]*3.5),int(oy+370-p[1]*3.5)) for p in contour],fill='#0582a3',width=4)
    d.text((ox+42,oy+65),f'z={z} mm | pink Hunyuan v2 | blue cover inner wall',fill='black')
canvas.save(HERE/'hunyuan_v2_section_fit.png')

heat=Image.new('RGB',(1200,760),'white');hd=ImageDraw.Draw(heat)
rows,cols=bin_min.shape
for jj in range(rows):
    for ii in range(cols):
        x0=90+ii*1000/cols;x1=90+(ii+1)*1000/cols
        y1=700-jj*620/rows;y0=700-(jj+1)*620/rows
        if not strong[jj,ii]:color='#eeeeee'
        else:
            value=float(np.clip(bin_min[jj,ii],-15,15))
            if value<0:color=(230,int(210+value*9),int(210+value*9))
            else:color=(int(210-value*9),int(210-value*4),230)
        hd.rectangle((x0,y0,x1,y1),fill=color)
hd.text((90,25),'Minimum radial gap: red = collision, blue = clearance, gray = sparse model samples',fill='black')
hd.text((90,715),'angle around corrected prosthesis axis, 122 to 418 deg',fill='black')
hd.text((10,680),'20 mm',fill='black');hd.text((10,75),'275 mm',fill='black')
heat.save(HERE/'hunyuan_v2_gap_map.png')

report={'model':'hunyuan31-v2-aligned-mm.stl','model_faces':len(model.faces),
    'coordinate_frame':'corrected prosthesis axis, mm',
    'cover':'photo_hull_body_shell.stl','covered_z_mm':[float(zs[0]),float(zs[-1])],
    'sample_count':int(len(gap)),'negative_radial_gap_count':int((gap<0).sum()),
    'negative_radial_gap_fraction':round(float((gap<0).mean()),5),
    'gap_mm':{'min':round(float(gap.min()),2),'p01':round(float(np.quantile(gap,.01)),2),
        'median':round(float(np.median(gap)),2),'p99':round(float(np.quantile(gap,.99)),2)},
    'zones':zones,'bins_with_20_or_more_samples':int(strong.sum()),
    'penetrating_bins':int(bad.sum()),
    'basis':'radial comparison in active shell cells, excluding the open bolt notch and AI shoe/hand outside shell height',
    'limitations':['Hunyuan dimensions and registration are approximate','Hunyuan itself differs from the scanned real prosthesis','radial gap is not a full insertion or fastening simulation','upper rim absent from this shell']}
(HERE/'hunyuan_v2_fit_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
