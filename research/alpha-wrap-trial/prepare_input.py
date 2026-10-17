"""Prepare train/held-out scan points in the corrected axis millimetre frame."""
import json
import sys
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT/'pointcloud-contour-prototype'))
import build_partial_shell as partial

cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
points=partial.load_points(cfg)
initial=len(points)
points=points[(points[:,2]>=20)&(points[:,2]<=275)]
green=np.load(ROOT/'photo-hull-cover/green_profiles.npz')
z=green['z_mm'];centers=green['center_xy_mm']
c=np.column_stack([np.interp(points[:,2],z,centers[:,j]) for j in range(2)])
xy=points[:,:2]-c
bearing=np.arctan2(xy[:,1],xy[:,0])
radius=np.linalg.norm(xy,axis=1)
fastener=(np.abs(np.angle(np.exp(1j*(bearing-np.pi))))<np.deg2rad(25))&(points[:,2]<85)
points=points[~fastener&(radius<80)]
before_outliers=len(points)
tree=cKDTree(points)
dist,_=tree.query(points,k=12,workers=-1)
nn=dist[:,-1]
keep=np.ones(len(points),bool)
for lo,hi in [(20,90),(90,150),(150,230),(230,276)]:
    band=(points[:,2]>=lo)&(points[:,2]<hi)
    keep[band]=nn[band]<=np.quantile(nn[band],.995)
points=points[keep]
rng=np.random.default_rng(20260929)
holdout=rng.random(len(points))<.2
train=points[~holdout]
test=points[holdout]
np.savetxt(HERE/'train_points.xyz',train,fmt='%.6f')
np.savez_compressed(HERE/'input_points.npz',train=train,holdout=test)
report={'source':cfg['source'],'coordinates':'corrected axis frame, millimetres',
        'initial_scan_points':initial,'z20_275_points':before_outliers,
        'after_outlier_removal':len(points),'train_points':len(train),
        'holdout_points':len(test),'excluded_fastener':'angle +/-25 deg from -X below z85 mm',
        'outlier_filter':'remove upper 0.5% of 12th nearest-neighbor distances per height band',
        'seed':20260929}
(HERE/'input_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
