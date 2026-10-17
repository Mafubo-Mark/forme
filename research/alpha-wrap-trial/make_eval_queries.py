"""Use identical held-out scan and Hunyuan points for wrapper and old-shell audits."""
import json
from pathlib import Path
import numpy as np
import trimesh

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
prof=np.load(ROOT/'photo-hull-cover/body_shell_profiles.npz')
zs=prof['z_mm'];angles=prof['angles_rad'];center=prof['centers_xy_mm'];inner=prof['inner_radius_mm'];active=prof['active_cells']

def select_and_gap(points):
    points=points[(points[:,2]>=30)&(points[:,2]<=265)]
    j=np.clip(np.searchsorted(zs,points[:,2])-1,0,len(zs)-2)
    bz=(points[:,2]-zs[j])/(zs[j+1]-zs[j])
    c=center[j]*(1-bz[:,None])+center[j+1]*bz[:,None]
    rel=points[:,:2]-c
    r=np.linalg.norm(rel,axis=1)
    a=np.mod(np.arctan2(rel[:,1],rel[:,0])-angles[0],2*np.pi)+angles[0]
    i=np.clip(np.searchsorted(angles,a)-1,0,len(angles)-2)
    choose=(a<=angles[-1])&(r<100)&active[j,i]
    points,j,bz,r,a,i=(q[choose] for q in (points,j,bz,r,a,i))
    ba=(a-angles[i])/(angles[i+1]-angles[i])
    ir=(inner[j,i]*(1-bz)*(1-ba)+inner[j+1,i]*bz*(1-ba)
       +inner[j,i+1]*(1-bz)*ba+inner[j+1,i+1]*bz*ba)
    return points,ir-r

scan=np.load(HERE/'input_points.npz')['holdout']
scan,scan_gap=select_and_gap(scan)
iso=json.loads((ROOT/'analysis/isolation-config.json').read_text())
mm=json.loads((ROOT/'analysis/scale-calibration.json').read_text())['mm_per_colmap_unit']
cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
mesh=trimesh.load(ROOT/'hunyuan31-v2-comparison/hunyuan31-v2-aligned-mm.stl',process=False)
sample,_=trimesh.sample.sample_surface(mesh,200000,seed=20260929)
axis=np.asarray(iso['axis_colmap'],float);axis/=np.linalg.norm(axis)
x=np.cross(axis,[1.,0.,0.]);x/=np.linalg.norm(x)
y=np.cross(axis,x)
basis=np.stack([x,y,-axis],axis=1)
world=np.asarray(iso['origin_colmap'])+(sample/mm)@basis.T
frame=np.array([cfg['x_in_input_coordinates'],cfg['front_in_input_coordinates'],cfg['axis_in_input_coordinates']]).T
model=(world-np.asarray(cfg['origin_in_input_coordinates']))@frame*cfg['input_to_mm_scale']
model[:,2]-=cfg['trim_low_input_coordinate']*cfg['input_to_mm_scale']+cfg['cover_start_mm']
model,model_gap=select_and_gap(model)
all_points=np.vstack([scan,model])
np.savetxt(HERE/'eval_queries.xyz',all_points,fmt='%.6f')
np.savez_compressed(HERE/'eval_reference.npz',scan_count=len(scan),scan_gap_old=scan_gap,
                    model_gap_old=model_gap,scan=scan,model=model)
print({'heldout_scan_points':len(scan),'hunyuan_points':len(model),
       'old_scan_min_gap_mm':round(float(scan_gap.min()),2),
       'old_model_min_gap_mm':round(float(model_gap.min()),2)})
