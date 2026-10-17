from pathlib import Path
import numpy as np,json,trimesh
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import gaussian_filter1d
import sys
O=Path(sys.argv[1]).resolve();cfg=json.loads((O/'run_config.json').read_text());R=Path(cfg['referenceRoot']);rows=json.loads((R/'observed_upper_rim.json').read_text());angles=np.radians([p['angle'] for p in rows]);observed=np.array([p['upperZP99_5'] for p in rows]);smooth=gaussian_filter1d(observed,.6,mode='wrap');cap=np.minimum(observed,smooth)-float(cfg['rimExposureMm']);pchip=PchipInterpolator(np.r_[angles[-3:]-2*np.pi,angles,angles[:3]+2*np.pi],np.r_[cap[-3:],cap,cap[:3]])
N=180;a=np.linspace(-np.pi,np.pi,N,endpoint=False);top=pchip(a);radii=[1.,10.,20.,30.,40.,50.,60.,70.,80.,90.,110.,150.];vertices=[]
for radius in radii:
 vertices.extend(np.c_[cfg['centerXYMm'][0]+radius*np.cos(a),cfg['centerXYMm'][1]+radius*np.sin(a),top].tolist())
bottom_start=len(vertices);vertices.extend(np.c_[cfg['centerXYMm'][0]+150*np.cos(a),cfg['centerXYMm'][1]+150*np.sin(a),np.full(N,-200.)].tolist());top_center=len(vertices);vertices.append([*cfg['centerXYMm'],float(top.min())]);bottom_center=len(vertices);vertices.append([*cfg['centerXYMm'],-200.]);faces=[]
for k in range(len(radii)-1):
 for i in range(N):
  j=(i+1)%N;inner=k*N;outer=(k+1)*N;faces.extend([[outer+i,outer+j,inner+j],[outer+i,inner+j,inner+i]])
for i in range(N):
 j=(i+1)%N;outer=(len(radii)-1)*N;faces.extend([[top_center,i,j],[bottom_center,bottom_start+j,bottom_start+i],[bottom_start+i,bottom_start+j,outer+j],[bottom_start+i,outer+j,outer+i]])
mesh=trimesh.Trimesh(vertices=vertices,faces=faces,process=True)
if mesh.volume<0:mesh.invert()
assert mesh.is_watertight and mesh.is_winding_consistent;mesh.export(O/'rim_limit_volume.stl');report={'method':'outer angular point-cloud upper-height .995 quantile, reviewed against task-specific original-camera overlays; light periodic smoothing capped by observed quantile; PCHIP angular interpolation','observedAngularRim':rows,'nominalExposedRimMm':cfg['rimExposureMm'],'capAnglesDeg':np.degrees(a).tolist(),'capHeightMm':top.tolist(),'capMinMaxMm':[float(top.min()),float(top.max())],'operation':'intersect candidate with solid below this angular rim; only removes existing geometry, does not extend template height','scope':'paper-covered reconstructed edge; not independently measured bare socket edge'};(O/'rim_trim_proposal.json').write_text(json.dumps(report,indent=2));print('capheight',report['capMinMaxMm'])
