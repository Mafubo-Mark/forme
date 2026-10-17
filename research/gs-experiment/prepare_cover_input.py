"""Filter test4 3DGS centers and configure an explicitly provisional CAD draft."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement

ROOT=Path('/Volumes/extra/workspace1/projects/test4')
BASE=ROOT/'gs-experiment'
raw=PlyData.read(str(BASE/'run-alpha-5000/export_5000.ply'))['vertex'].data
xyz=np.column_stack([raw[k] for k in ('x','y','z')]).astype(np.float64)
scale=np.exp(np.column_stack([raw[k] for k in ('scale_0','scale_1','scale_2')]))
roi=json.loads((ROOT/'analysis/isolation-config.json').read_text())
axis=np.asarray(roi['axis_colmap'],float)
origin=np.asarray(roi['origin_colmap'],float)
delta=xyz-origin
axial=delta@axis
radial=np.linalg.norm(delta-axial[:,None]*axis,axis=1)
keep=(np.isfinite(xyz).all(axis=1)&(raw['opacity']>-1.8)&
      (np.max(scale,axis=1)<0.055)&
      (axial>-0.55)&(axial<2.32)&(radial<0.69))
chosen=raw[keep]
out=np.empty(len(chosen),dtype=[('x','f4'),('y','f4'),('z','f4')])
for field in out.dtype.names:
    out[field]=chosen[field]
dest=BASE/'gs-surface-centers.ply'
PlyData([PlyElement.describe(out,'vertex')],text=False).write(str(dest))

prior=json.loads((ROOT/'cad-review/sections.json').read_text())
cfg=json.loads((ROOT/'cad-review/config.json').read_text())
cfg['input_path']=str(dest)
cfg['fixed_origin_input_coordinates']=prior['origin_in_input_coordinates']
lo=prior['trim_low_input_coordinate']
hi=lo+prior['measured_span_mm']/prior['input_to_mm_scale']
cfg['fixed_axis_bounds_input']=[lo,hi]
cfg['xy_low_percentile']=2.5
cfg['xy_high_percentile']=97.5
cfg['ellipse_enclosure_percentile']=90
cfg['max_ellipse_expansion']=1.08
cfg['minimum_points_per_station']=80
cfg['station_median_window']=5
cfg['station_smoothing_sigma']=1.2
cfg['preserve_station_envelope']=False
cfg['opening_angle_deg']=28
cfg['opening_center_deg']=0
cfg['loft_ruled']=True
cfg['station_count']=25
# Estimate an upper-rim plane from high-opacity 3DGS centers in angular bins.
# This captures the measured slant while keeping the Boolean CAD top surface planar.
axis_basis=np.stack([prior['x_in_input_coordinates'],
                     prior['front_in_input_coordinates'],
                     prior['axis_in_input_coordinates']],axis=1)
local=(xyz[keep]-np.asarray(prior['origin_in_input_coordinates']))@axis_basis
local*=prior['input_to_mm_scale']
local[:,2]-=prior['trim_low_input_coordinate']*prior['input_to_mm_scale']+prior['cover_start_mm']
top_center=prior['stations'][-1]
theta=(np.rad2deg(np.arctan2(local[:,1]-top_center['center_y_mm'],
                            local[:,0]-top_center['center_x_mm']))+360)%360
rim_samples=[]
for angle in range(0,360,15):
    slab=local[(theta>=angle)&(theta<angle+15)&(local[:,2]>300)]
    if len(slab)<50:
        continue
    high=slab[slab[:,2]>np.percentile(slab[:,2],92)]
    rim_samples.append(np.median(high,axis=0))
rim=np.asarray(rim_samples)
if len(rim)<10:
    raise RuntimeError('Insufficient 3DGS upper-rim observations for sloped trim')
design=np.column_stack([np.ones(len(rim)),rim[:,:2]])
coeff=np.linalg.lstsq(design,rim[:,2],rcond=None)[0]
residual=float(np.std(rim[:,2]-design@coeff))
if residual>12 or max(abs(coeff[1]),abs(coeff[2]))>0.5:
    raise RuntimeError('Upper-rim plane is too uncertain for automatic trim')
cfg['top_rim_plane_mm']={
    'intercept_mm':round(float(coeff[0]-8),4),
    'slope_x':round(float(coeff[1]),6),
    'slope_y':round(float(coeff[2]),6),
    'extension_mm':90,
    'fit_residual_mm':round(residual,3),
    'below_observed_rim_mm':8
}
cfg['profile_reliefs']=[]
for pattern in cfg.get('cutouts',{}).get('hole_patterns',[]):
    if pattern.get('role')=='profile_relief_opening':
        pattern['role']='bolt_clearance_draft'
cfg['design_note']='3DGS Gaussian centers define a visual surface prior only; fit and material behavior require dimension checks and short physical trial print.'
draft=BASE/'cad-v4'
draft.mkdir(parents=True,exist_ok=True)
(draft/'config.json').write_text(json.dumps(cfg,indent=2,ensure_ascii=False)+'\n')
(BASE/'filter-report.json').write_text(json.dumps({
    'source_splats':len(raw),
    'kept_splats':len(chosen),
    'opacity_logit_min':-1.8,
    'maximum_axis_scale_colmap_units':0.055,
    'coordinate_frame':'same calibrated COLMAP world coordinates',
    'warning':'Gaussian centers are not a measured physical surface'
},indent=2)+'\n')
print('3DGS filtered centers:',len(chosen),'of',len(raw))
print('input:',dest)
print('config:',draft/'config.json')
