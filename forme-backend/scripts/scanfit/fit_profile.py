from pathlib import Path
import json,hashlib
import numpy as np,trimesh
from scipy.spatial import cKDTree,ConvexHull
from scipy.interpolate import griddata,RegularGridInterpolator,RectBivariateSpline
from scipy.ndimage import gaussian_filter
from scipy.optimize import lsq_linear
from scipy.sparse import lil_matrix,eye,vstack,diags
import sys
OUT=Path(sys.argv[1]).resolve();CFG=json.loads((OUT/'run_config.json').read_text());TASK=Path(CFG['referenceRoot']);CENTER=np.array(CFG['centerXYMm']);BOTTOM=float(CFG['bottomZMm']);EXT=-BOTTOM;TRANS=float(CFG['transitionZMm']);Z=np.arange(BOTTOM,321.,10.);A=-np.pi+(np.arange(36)+.5)*2*np.pi/36;CLEARANCE=float(CFG['clearanceMm'])

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fill(raw):
 zz,aa=np.meshgrid(Z,A,indexing='ij');mask=np.isfinite(raw);xy=np.c_[zz[mask],aa[mask]*50];v=raw[mask]
 pts=np.vstack([xy+np.array([0,shift*50]) for shift in [-2*np.pi,0,2*np.pi]]);values=np.tile(v,3);q=np.c_[zz.ravel(),aa.ravel()*50];out=griddata(pts,values,q,method='linear');missing=~np.isfinite(out);out[missing]=griddata(pts,values,q[missing],method='nearest');return out.reshape(raw.shape)
def interpolation(field):
 padded=np.c_[field[:,-4:],field,field[:,:4]];angles=np.r_[A[-4:]-2*np.pi,A,A[:4]+2*np.pi]
 spline=RectBivariateSpline(Z,angles,padded,kx=3,ky=3,s=0)
 return lambda coords:spline.ev(coords[:,0],coords[:,1])
def radial_query(interp,xyz):
 d=xyz[:,:2]-CENTER;a=np.arctan2(d[:,1],d[:,0]);return interp(np.c_[np.clip(xyz[:,2],Z[0],Z[-1]),a])
def source_profile(meshes):
 raw=np.full((len(Z),len(A)),np.nan)
 for i,z in enumerate(Z):
  segments=np.concatenate([trimesh.intersections.mesh_plane(m,[0,0,1],[0,0,float(np.clip(z,BOTTOM+.1,314.9))])[:,:,:2] for m in meshes]);starts=segments[:,0]-CENTER;v=segments[:,1]-segments[:,0]
  for j,a in enumerate(A):
   d=np.array([np.cos(a),np.sin(a)]);den=d[0]*v[:,1]-d[1]*v[:,0];valid=abs(den)>1e-9;t=np.full(len(den),np.nan);u=t.copy();t[valid]=(starts[valid,0]*v[valid,1]-starts[valid,1]*v[valid,0])/den[valid];u[valid]=(starts[valid,0]*d[1]-starts[valid,1]*d[0])/den[valid];hits=t[(t>0)&(u>=0)&(u<=1)];
   if len(hits):raw[i,j]=min(hits)
 return raw
cloud=np.load(TASK/'subject_upright_mm.npz')['xyz'];selected=cloud[(cloud[:,2]>=BOTTOM-12)&(cloud[:,2]<=332)];dist,_=cKDTree(selected).query(selected,k=13,workers=4);threshold=float(np.quantile(dist[:,-1],.98));points=selected[dist[:,-1]<=threshold];bolt=np.array(CFG['bolt']['baseMm']);axis=np.array(CFG['bolt']['axis']);diff=points-bolt;along=diff@axis;perp=np.linalg.norm(diff-along[:,None]*axis,axis=1);points=points[~((perp<CFG['bolt']['diameterMm']/2+8)&(along>-12))];rng=np.random.default_rng(1610);order=rng.permutation(len(points));cut=int(.8*len(points));train=points[order[:cut]];heldout=points[order[cut:]]
d=train[:,:2]-CENTER;r=np.linalg.norm(d,axis=1);a=np.arctan2(d[:,1],d[:,0]);raw=np.full((len(Z),len(A)),np.nan);count=np.zeros(raw.shape,int)
for i,z in enumerate(Z):
 near=abs(train[:,2]-z)<=8
 for j,angle in enumerate(A):
  sel=near&(abs(np.arctan2(np.sin(a-angle),np.cos(a-angle)))<=np.pi/36);n=int(sel.sum());count[i,j]=n
  if n>=8:raw[i,j]=np.quantile(r[sel],.98)
observed=np.isfinite(raw)
# Constrain missing angular cells with the convex envelope of THIS height band.
# A hull edge across a missing sector is an inferred chord, not measured anatomy.
hull_profile=np.full(raw.shape,np.nan);hull_center_inside=[]
for i,z in enumerate(Z):
 xy=train[abs(train[:,2]-z)<=8,:2];hull=ConvexHull(xy);polygon=xy[hull.vertices];inside=bool(np.max(hull.equations[:,:2]@CENTER+hull.equations[:,2])<=1e-6);hull_center_inside.append(inside)
 if not inside:continue
 starts=polygon-CENTER;v=np.roll(polygon,-1,axis=0)-polygon
 for j,angle in enumerate(A):
  d=np.array([np.cos(angle),np.sin(angle)]);den=d[0]*v[:,1]-d[1]*v[:,0];valid=abs(den)>1e-9;t=np.full(len(v),np.nan);u=t.copy();t[valid]=(starts[valid,0]*v[valid,1]-starts[valid,1]*v[valid,0])/den[valid];u[valid]=(starts[valid,0]*d[1]-starts[valid,1]*d[0])/den[valid];hits=t[(t>0)&(u>=0)&(u<=1)]
  if len(hits):hull_profile[i,j]=min(hits)
hull_profile=fill(hull_profile);smooth=gaussian_filter(hull_profile,sigma=(.65,.85),mode=('nearest','wrap'));surface=np.minimum(np.where(observed,np.maximum(smooth,raw),smooth),hull_profile);surface=gaussian_filter(surface,sigma=(2.,1.2),mode=('nearest','wrap'));target=np.where(observed,np.minimum(raw,hull_profile)+CLEARANCE,surface+CLEARANCE)
# Solve a smooth profile with observed outer-radius lower bounds. This prevents
# denoising from shrinking supported regions back through the cloud envelope.
n=target.size;rows=[];cols=[];vals=[];row=0
for i in range(1,len(Z)-1):
 for j in range(len(A)):
  for ii,vv in [(i-1,1),(i,-2),(i+1,1)]:rows.append(row);cols.append(ii*len(A)+j);vals.append(vv*2.)
  row+=1
for i in range(len(Z)):
 for j in range(len(A)):
  for jj,vv in [((j-1)%len(A),1),(j,-2),((j+1)%len(A),1)]:rows.append(row);cols.append(i*len(A)+jj);vals.append(vv*2.)
  row+=1
from scipy.sparse import coo_matrix
D=coo_matrix((vals,(rows,cols)),shape=(row,n)).tocsr();weights=np.where(observed,1.,.35).ravel();W=diags(weights)
lower=np.where(observed,np.minimum(raw,hull_profile)+CLEARANCE,8.).ravel();upper=np.full(n,np.inf)
solution=lsq_linear(vstack([W,D]),np.r_[target.ravel()*weights,np.zeros(row)],bounds=(lower,upper),tol=1e-7,lsmr_tol=1e-7,max_iter=100)
assert solution.success,solution.message
target=solution.x.reshape(target.shape)
meshes=[trimesh.load_mesh(OUT/'symmetric_base'/f'{side}.stl',process=True) for side in ['front','rear']]
# Extend only lower 100 mm of style template; upper body/rim coordinates stay anchored.
for m in meshes:
 z=m.vertices[:,2].copy();m.vertices[:,2]=np.where(z<TRANS,BOTTOM+(TRANS-BOTTOM)/TRANS*z,z)
base_audit={}
for side,mesh in zip(['front','rear'],meshes):
 mirrored=mesh.vertices.copy();mirrored[:,0]*=-1;distance,_=cKDTree(mesh.vertices).query(mirrored,workers=4)
 base_audit[side]={'watertight':bool(mesh.is_watertight),'windingConsistent':bool(mesh.is_winding_consistent),'components':len(mesh.split(only_watertight=False)),'maxMirrorVertexDistanceMm':float(distance.max()),'lowerZExtensionMm':EXT}
 assert mesh.is_watertight and mesh.is_winding_consistent and len(mesh.split(only_watertight=False))==1
 assert distance.max()<1e-4
print('SYMMETRIC BASE',base_audit,flush=True)
src_raw=source_profile(meshes);src=gaussian_filter(fill(src_raw),sigma=(.9,.65),mode=('nearest','wrap'));delta=target-src;warp=interpolation(delta);results={}
for side,mesh in zip(['front','rear'],meshes):
 old=mesh.vertices.copy();d=old[:,:2]-CENTER;r=np.linalg.norm(d,axis=1);offset=radial_query(warp,old);newr=r+offset;assert newr.min()>1
 mesh.vertices[:,:2]=CENTER+d*(newr/r)[:,None];mesh.export(OUT/f'cover_{side}_mm.stl');mesh2=trimesh.load_mesh(OUT/f'cover_{side}_mm.stl',process=True)
 results[side]={'file':f'cover_{side}_mm.stl','sha256':sha(OUT/f'cover_{side}_mm.stl'),'watertight':bool(mesh2.is_watertight),'consistentWinding':bool(mesh2.is_winding_consistent),'components':len(mesh2.split(only_watertight=False)),'boundsMm':mesh2.bounds.tolist(),'maxMoveFromSymmetricBaseMm':float(abs(offset).max()),'minRadialJacobianRatio':float((newr/r).min()),'maxZChangeMm':float(abs(mesh2.bounds[:,2]-mesh.bounds[:,2]).max())}
 assert mesh2.is_watertight and mesh2.is_winding_consistent and results[side]['components']==1
trimesh.util.concatenate(meshes).export(OUT/'cover_combined_assembly_mm.stl')
# Evaluate using the OUTPUT STL sections, not the requested target profile alone.
actual_raw=source_profile(meshes);actual_interp=interpolation(fill(actual_raw));diagnostics={}
for name,p in [('train',train),('heldout',heldout),('allRegisteredInHeight',selected)]:
 pp=p[(p[:,2]>=BOTTOM)&(p[:,2]<=315)];rad=np.linalg.norm(pp[:,:2]-CENTER,axis=1);gap=radial_query(actual_interp,pp)-rad
 diagnostics[name]={'pointCount':len(pp),'radialGapQuantilesMm':dict(zip(['min','p01','p05','median','p95','max'],np.quantile(gap,[0,.01,.05,.5,.95,1]).tolist())),'fractionNegativeGap':float((gap<0).mean()),'fractionGapBelow1mm':float((gap<1).mean()),'method':'radial first mesh hit interpolated from output STL sections; vents, fasteners, source interior/outliers and sparse directions limit interpretation; not signed-distance collision proof'}
report={'candidateId':OUT.name,'status':'EXPERIMENTAL_POINTCLOUD_FIT_NOT_PHYSICALLY_VERIFIED','sourceTemplate':CFG['templateId'],'sourceVideoSha256':CFG['sourceVideoSha256'],'hunyuanUsed':False,'oldVideoPointcloudUsed':False,'registrationScope':'new-video geometric frame, not fit approval','units':'mm','symmetryBase':base_audit,'pointcloud':{'file':'subject_upright_mm.npz','sha256':sha(TASK/'subject_upright_mm.npz'),'geometryFrameSha256':sha(TASK/'geometry_review.json'),'sourceCropSha256':CFG['rawCloudSha256'],'registrationSha256':sha(TASK/'geometry_review.json'),'rulerCalibrationSha256':sha(TASK/'ruler_calibration_extended.json'),'inputCount':len(cloud),'heightBandCount':len(selected),'densityFilteredCount':len(points),'densityFilterK':12,'densityFilterDistanceP98Mm':threshold,'trainCount':len(train),'heldoutCount':len(heldout)},'profile':{'zSpacingMm':10,'angleSpacingDeg':10,'heightHalfBandMm':8,'minimumPointsPerCell':8,'outerRadialQuantile':.98,'nominalTrialClearanceMm':CLEARANCE,'dataFidelity':'direct observed outer quantile in supported cells; smoothed hull only in unsupported cells','legacySeedAxialGaussianSigmaMm':20,'legacySeedAngularGaussianSigmaDeg':12,'smoothingNote':'bounded sparse least-squares profile: observed outer-quantile lower bounds plus axial/circular second-difference penalties (2 and 2); interpolated gaps remain inferred; not exact interpolation of individual points','smoothingSolverCost':float(solution.cost),'observedCells':int(observed.sum()),'totalCells':observed.size,'interpolatedCells':int((~observed).sum()),'sourceMeshObservedCells':int(np.isfinite(src_raw).sum()),'finalSymmetry':'symmetric base; data-driven warp may be asymmetric','hullCenterInsideAtAllHeights':all(hull_center_inside),'missingSectorMethod':'same-height point-cloud convex-hull chord with light smoothing; not a verified unseen surface','method':'same-height cloud convex hull constrains outer-radius profile; observed 98th radial quantiles constrain smoothing; inferred sectors initially capped by local hull, followed by low-frequency regularization and curvature-penalized least squares with observed radius lower bounds; periodic cubic radial offset shared by both halves; no Hunyuan shape, no 3mm bound, no upper-rim freeze','features':'existing template ribs, apertures and latch geometry warped together; latch function not validated'},'parts':results,'outputSectionDiagnostics':diagnostics,'physicalFitVerified':False,'manufacturingApproved':False,'blockers':['REFERENCE_POINTCLOUD_LOCAL_ACCURACY_UNVERIFIED','SPARSE_PROFILE_CELLS_INTERPOLATED','RADIAL_SINGLE_VALUED_SURFACE_ASSUMPTION','PRINT_SCALE_NOT_CONFIRMED','SELF_INTERSECTION_AND_WALL_THICKNESS_REVIEW','WARPED_FASTENER_FUNCTION_UNVERIFIED','FIT_COUPON_REQUIRED_BEFORE_FULL_PRINT']}
(OUT/'build_report.json').write_text(json.dumps(report,indent=2));np.savez(OUT/'radial_profiles.npz',z=Z,angles=A,sourceRaw=src_raw,source=src,observedRaw=raw,observedCount=count,observedMask=observed,hullProfile=hull_profile,target=target,offset=delta,actualRaw=actual_raw);print(json.dumps(report,indent=2),flush=True)
