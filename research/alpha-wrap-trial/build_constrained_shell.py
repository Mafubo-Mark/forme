"""Minimal smooth inflation of the existing C shell to enclose a CGAL wrap.

The QP is a standard bound-constrained membrane fairing problem.  The CGAL
outer profile is a hard lower bound; smoothness acts only on the correction.
"""
import json
import sys
from pathlib import Path
import numpy as np
import trimesh
from scipy.optimize import minimize
from scipy.spatial import ConvexHull

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT/'photo-hull-cover'))
sys.path.insert(0,str(ROOT/'pointcloud-full-cover-prototype'))
sys.path.insert(0,str(ROOT/'pointcloud-contour-prototype'))
from build_photo_hull_profiles import ray_polygon
import build_full_cover as full
import build_partial_shell as partial

data=np.load(ROOT/'photo-hull-cover/body_shell_profiles.npz')
z=data['z_mm'];a=data['angles_rad'];centers=data['centers_xy_mm'];old=data['inner_radius_mm'];active=data['active_cells']
wrap=trimesh.load(HERE/'union_a8_o7.off',process=False)
wrap_r=[]
for height,center in zip(z,centers):
    section=wrap.section(plane_origin=[0,0,float(height)],plane_normal=[0,0,1])
    if section is None:raise ValueError(f'No CGAL section at {height}')
    loops=[]
    for curve in section.discrete:
        poly=curve[:,:2]
        area=abs(np.sum(poly[:,0]*np.roll(poly[:,1],-1)-poly[:,1]*np.roll(poly[:,0],-1))/2)
        loops.append((area,poly))
    # Several bottom-level lobes can be disconnected by the bolt relief; the
    # enclosing radial body uses all boundary samples at that height.
    boundary=np.vstack([loop[1] for loop in loops])
    poly=boundary[ConvexHull(boundary).vertices]
    wrap_r.append(ray_polygon(poly,center,a))
wrap_r=np.asarray(wrap_r)

# L-BFGS-B enforces delta >= wrapped outer envelope + 0.5 mm.
lower=np.maximum(0,wrap_r-old+0.5)
shape=lower.shape
w0=1.0;wz=30.0;wa=80.0
def value_and_grad(flat):
    x=flat.reshape(shape)
    dz=np.diff(x,axis=0);da=np.diff(x,axis=1)
    val=.5*(w0*np.sum(x*x)+wz*np.sum(dz*dz)+wa*np.sum(da*da))
    grad=w0*x
    grad[:-1]-=wz*dz;grad[1:]+=wz*dz
    grad[:,:-1]-=wa*da;grad[:,1:]+=wa*da
    return val,grad.ravel()
res=minimize(value_and_grad,lower.ravel(),method='L-BFGS-B',jac=True,
             bounds=list(zip(lower.ravel(),np.full(lower.size,np.inf))),
             options={'maxiter':250,'ftol':1e-10})
delta=res.x.reshape(shape)
inner=old+delta
outer=inner+3
mesh=full.build_mesh(z,a,centers,inner,outer,active)
mesh.export(HERE/'constrained_body_shell.stl')
mesh.export(HERE/'constrained_body_shell.ply')
np.savez_compressed(HERE/'constrained_profiles.npz',z_mm=z,angles_rad=a,
                    centers_xy_mm=centers,inner_radius_mm=inner,outer_radius_mm=outer,
                    cgal_outer_radius_mm=wrap_r,correction_mm=delta,active_cells=active)
partial.ROOT=HERE
partial.render_mesh(mesh)
(HERE/'mesh_preview.png').rename(HERE/'constrained_shell_preview.png')

def radial_gap(points):
    j=np.clip(np.searchsorted(z,points[:,2])-1,0,len(z)-2)
    f=(points[:,2]-z[j])/(z[j+1]-z[j])
    c=centers[j]*(1-f[:,None])+centers[j+1]*f[:,None]
    rel=points[:,:2]-c
    ang=np.mod(np.arctan2(rel[:,1],rel[:,0])-a[0],2*np.pi)+a[0]
    i=np.clip(np.searchsorted(a,ang)-1,0,len(a)-2)
    b=(ang-a[i])/(a[i+1]-a[i])
    ir=(inner[j,i]*(1-f)*(1-b)+inner[j+1,i]*f*(1-b)
        +inner[j,i+1]*(1-f)*b+inner[j+1,i+1]*f*b)
    return ir-np.linalg.norm(rel,axis=1)

ref=np.load(HERE/'union_eval_reference.npz')
report={'status':'CONCEPT BODY SHELL; NOT MANUFACTURING FIT VERIFIED',
        'source_wrap':'union_a8_o7.off','method':'convex outer CGAL sections as hard lower bound; quadratic smooth inflation',
        'optimization_success':bool(res.success),'optimization_message':str(res.message),
        'watertight':bool(mesh.is_watertight),'components':len(mesh.split()),
        'correction_mm':{'max':round(float(delta.max()),2),'median':round(float(np.median(delta)),2),
                         'fraction_nonzero':round(float(np.mean(delta>0.01)),4)},
        'eval':{}}
for name in ['scan','model']:
    gaps=radial_gap(ref[name])
    report['eval'][name]={'n':len(gaps),'minimum_gap_mm':round(float(gaps.min()),2),
        'p01_gap_mm':round(float(np.quantile(gaps,.01)),2),
        'median_gap_mm':round(float(np.median(gaps)),2),
        'negative_count':int(np.count_nonzero(gaps<0)),
        'under_2mm_count':int(np.count_nonzero(gaps<2))}
(HERE/'constrained_shell_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
