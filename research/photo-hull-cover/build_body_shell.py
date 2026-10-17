"""Build a C-shell for the photo-supported lower/middle body only."""
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from scipy.ndimage import gaussian_filter1d

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT/'pointcloud-contour-prototype'))
sys.path.insert(0,str(ROOT/'pointcloud-full-cover-prototype'))
import build_partial_shell as partial
import build_full_cover as full


def interpolate_angles(values: np.ndarray, source_angles: np.ndarray,
                       target_angles: np.ndarray) -> np.ndarray:
    wrapped=np.r_[source_angles,2*np.pi]
    result=[]
    for row in values:
        result.append(np.interp(np.mod(target_angles,2*np.pi),wrapped,np.r_[row,row[0]]))
    return np.asarray(result)


def build() -> None:
    data=np.load(HERE/'green_profiles.npz')
    original_z=data['z_mm'];original_a=data['angles_rad']
    first=np.deg2rad(122)
    angles=np.linspace(first,first+2*np.pi-np.deg2rad(64),241)
    zs=np.arange(20,275.001,2.5)
    centers=np.column_stack([np.interp(zs,original_z,data['center_xy_mm'][:,j])
                             for j in range(2)])
    inner_full=np.column_stack([np.interp(zs,original_z,data['inner_radius_mm'][:,j])
                                for j in range(len(original_a))])
    outer_full=np.column_stack([np.interp(zs,original_z,data['outer_radius_mm'][:,j])
                                for j in range(len(original_a))])
    inner=interpolate_angles(inner_full,original_a,angles)
    outer=interpolate_angles(outer_full,original_a,angles)
    scan=partial.load_points(full.CONFIG)
    # A single smooth axial allowance handles the yellow transition band.
    # It is estimated from high-percentile scan excess over the photo hull;
    # no per-angle point-cloud bumps are transferred to the shell.
    band_allowance=[]
    for z,center,object_r in zip(original_z,data['center_xy_mm'],data['object_radius_mm']):
        if not 70<=z<=155:
            band_allowance.append(0.0)
            continue
        band=scan[np.abs(scan[:,2]-z)<4,:2]
        xy=band-center
        theta=np.mod(np.arctan2(xy[:,1],xy[:,0]),2*np.pi)
        model=np.interp(theta,np.r_[original_a,2*np.pi],np.r_[object_r,object_r[0]])
        excess=np.linalg.norm(xy,axis=1)-model
        band_allowance.append(max(0.0,float(np.quantile(excess,.995))-5.0+1.0))
    band_allowance=gaussian_filter1d(np.asarray(band_allowance),2.0,mode='constant')
    allowance=np.interp(zs,original_z,band_allowance)
    inner+=allowance[:,None]
    outer+=allowance[:,None]
    active=full.active_cells(zs,angles,np.full(len(angles),275.0))
    np.savez_compressed(HERE/'body_shell_profiles.npz',z_mm=zs,angles_rad=angles,
                        centers_xy_mm=centers,inner_radius_mm=inner,
                        outer_radius_mm=outer,transition_allowance_mm=allowance,
                        active_cells=active)
    mesh=full.build_mesh(zs,angles,centers,inner,outer,active)
    mesh.export(HERE/'photo_hull_body_shell.stl')
    mesh.export(HERE/'photo_hull_body_shell.ply')
    partial.ROOT=HERE
    partial.render_mesh(mesh)
    sample=scan[(scan[:,2]>=20)&(scan[:,2]<=275)]
    if len(sample)>100000:
        sample=sample[np.random.default_rng(16).choice(len(sample),100000,replace=False)]
    j=np.clip(np.searchsorted(zs,sample[:,2])-1,0,len(zs)-2)
    blend=(sample[:,2]-zs[j])/(zs[j+1]-zs[j])
    center=centers[j]*(1-blend[:,None])+centers[j+1]*blend[:,None]
    rel=sample[:,:2]-center
    angle=np.mod(np.arctan2(rel[:,1],rel[:,0])-angles[0],2*np.pi)+angles[0]
    include=angle<=angles[-1]
    bolt=(full.angular_distance(angle,np.pi)<np.deg2rad(21))&(sample[:,2]<78)
    include &= ~bolt
    sample,j,blend,angle,rel=sample[include],j[include],blend[include],angle[include],rel[include]
    i=np.clip(np.searchsorted(angles,angle)-1,0,len(angles)-2)
    beta=(angle-angles[i])/(angles[i+1]-angles[i])
    r=(inner[j,i]*(1-blend)*(1-beta)+inner[j+1,i]*blend*(1-beta)
       +inner[j,i+1]*(1-blend)*beta+inner[j+1,i+1]*blend*beta)
    gap=r-np.linalg.norm(rel,axis=1)
    negative_by_zone={}
    for lo,hi in ((20,90),(90,150),(150,275)):
        zone=(sample[:,2]>=lo)&(sample[:,2]<hi)
        negative_by_zone[f'{lo}-{hi}mm']={
            'sample_count':int(np.count_nonzero(zone)),
            'negative_radial_gaps':int(np.count_nonzero((gap<0)&zone))}
    negative_z_hist,negative_z_edges=np.histogram(sample[gap<0,2],bins=np.arange(20,281,10))
    report={"status":"PHOTO-HULL BODY SHELL PROTOTYPE; UPPER RIM NOT MODELED; NOT FIT VERIFIED",
            "z_range_mm":[20,275],"mesh_extents_mm":np.round(mesh.extents,2).tolist(),
            "watertight":bool(mesh.is_watertight),"components":len(mesh.split(only_watertight=False)),
            "mesh_volume_mm3":round(float(mesh.volume),1),
            "sampled_scan_points":len(gap),"radial_gap_p01_mm":round(float(np.quantile(gap,.01)),2),
            "radial_gap_min_mm":round(float(gap.min()),2),
            "negative_radial_gaps":int(np.count_nonzero(gap<0)),
            "negative_gap_by_zone":negative_by_zone,
            "negative_gap_z_10mm_bins":{f'{int(lo)}-{int(hi)}':int(n) for lo,hi,n in
                zip(negative_z_edges[:-1],negative_z_edges[1:],negative_z_hist) if n},
            "smooth_transition_band_allowance_max_mm":round(float(allowance.max()),2),
            "bolt_relief":"provisional lower open notch; fastener not measured"}
    (HERE/'body_shell_validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    build()
