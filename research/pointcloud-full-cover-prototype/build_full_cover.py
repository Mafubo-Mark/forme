"""Full-length scan-derived cover concept with open bolt relief and shaped rim.

This is a geometric feasibility model, not a verified fit or measured bolt cutout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import cv2
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter, gaussian_filter1d, maximum_filter1d
from scipy.spatial import ConvexHull
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pointcloud-contour-prototype"))
import build_partial_shell as base

CONFIG = json.loads((HERE.parent / "pointcloud-axis-corrected" / "sections.json").read_text())
OPENING_CENTER_DEG = 90
OPENING_DEG = 64
ANGLE_COUNT = 241
BOTTOM_MM = 20.0
LOWER_PROFILE_TOP_MM = 275.0
TOP_GRID_MM = 367.5
GRID_STEP_MM = 1.25
BOLT_ANGLE_DEG = 180.0
BOLT_NOTCH_HALF_ANGLE_DEG = 21.0
BOLT_NOTCH_TOP_MM = 78.0
BOLT_NOTCH_ROUND_MM = 20.0


def angular_distance(a: np.ndarray, b: float) -> np.ndarray:
    return np.abs(np.angle(np.exp(1j*(a-b))))


def lower_profiles(points: np.ndarray, angles: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict]]:
    zs = np.arange(BOTTOM_MM, LOWER_PROFILE_TOP_MM+.01, 7.5)
    centers, inners, outers, reports = [], [], [], []
    for z in zs:
        old = min(CONFIG["stations"], key=lambda s: abs(s["height_mm"]-z))
        center = np.array([old["center_x_mm"], old["center_y_mm"]])
        if z < 95:
            inner, outer, report = lower_convex_fallback(points, z, center, angles)
        else:
            try:
                inner, outer, report = base.section(points, z, center, angles, min_angular_bins=20)
            except ValueError as exc:
                raise ValueError(f"Cannot extract lower contour at z={z}: {exc}") from exc
        # The metal stud is a separate object. Estimate the underlying side
        # only inside a wider open-to-bottom relief that removes these cells.
        if 25 <= z <= 75:
            inside = angular_distance(angles, np.pi) < np.deg2rad(24)
            edge = np.flatnonzero(~inside)
            left, right = edge[edge < np.flatnonzero(inside)[0]][-1], edge[edge > np.flatnonzero(inside)[-1]][0]
            for radius in (inner, outer):
                radius[inside] = np.interp(angles[inside],
                                           [angles[left], angles[right]],
                                           [radius[left], radius[right]])
        centers.append(center)
        inners.append(inner)
        outers.append(outer)
        reports.append(report)
    inners = gaussian_filter(maximum_filter1d(np.asarray(inners), 5, axis=0, mode="nearest"),
                            (2.2, 1.5), mode="nearest")
    outers = gaussian_filter(maximum_filter1d(np.asarray(outers), 5, axis=0, mode="nearest"),
                            (2.2, 1.5), mode="nearest")
    return zs, np.asarray(centers), np.stack((inners, outers)), reports


def lower_convex_fallback(points: np.ndarray, z: float, center: np.ndarray,
                          angles: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Close the incomplete white-cylinder scan with a marked convex envelope."""
    band = points[np.abs(points[:, 2]-z) <= 4, :2]
    if 25 <= z <= 75:
        a = np.arctan2(band[:, 1]-center[1], band[:, 0]-center[0])
        stud = (angular_distance(a, np.pi) < np.deg2rad(25)) & (band[:, 0] < -48)
        band = band[~stud]
    if len(band) < 400:
        raise ValueError(f"Too few lower-body points at z={z}")
    lo, hi = np.quantile(band, [.005, .995], axis=0)
    band = band[np.all((band >= lo) & (band <= hi), axis=1)]
    hull = ConvexHull(band)
    n = round(2*base.GRID_HALF_MM/base.GRID_MM)+1
    pixels = np.rint((band[hull.vertices] + np.array([base.GRID_HALF_MM,-base.GRID_HALF_MM]))
                      * np.array([1,-1])/base.GRID_MM).astype(np.int32)
    filled = np.zeros((n,n),np.uint8)
    cv2.fillConvexPoly(filled,pixels,255)
    observed = base.radial_profile(base.largest_contour(filled),center,angles)
    inner_mask=cv2.dilate(filled,base.kernel(7.0))
    outer_mask=cv2.dilate(filled,base.kernel(10.0))
    inner=base.radial_profile(base.largest_contour(inner_mask),center,angles)
    outer=base.radial_profile(base.largest_contour(outer_mask),center,angles)
    bins,_=np.histogram(np.mod(np.arctan2(band[:,1]-center[1],band[:,0]-center[0]),2*np.pi),
                        bins=24,range=(0,2*np.pi))
    return inner,outer,{"z_mm":float(z),"method":"convex closure of incomplete lower-body scan",
                        "points_in_band":len(band),"angular_bins_with_15_points_of_24":int(np.count_nonzero(bins>=15)),
                        "observed_radius_min_mm":round(float(observed.min()),2),
                        "observed_radius_max_mm":round(float(observed.max()),2)}


def observed_upper_rim(points: np.ndarray, angles: np.ndarray, center: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    high = points[points[:, 2] > 260]
    bearing = np.mod(np.arctan2(high[:, 1]-center[1], high[:, 0]-center[0]), 2*np.pi)
    radius = np.linalg.norm(high[:, :2]-center, axis=1)
    heights = np.zeros(len(angles))
    counts = np.zeros(len(angles), dtype=int)
    for i, a in enumerate(angles):
        m = (angular_distance(bearing, a) <= np.deg2rad(3.5)) & (radius > 35)
        vals = high[m, 2]
        counts[i] = len(vals)
        if len(vals) < 30:
            raise ValueError(f"Too little upper-rim evidence at angle {np.rad2deg(a)%360:.1f}")
        heights[i] = np.quantile(vals, .98) - 4.0
    heights = gaussian_filter1d(heights, 5.0, mode="nearest")
    heights = np.clip(heights, 278, 365)
    return heights, counts


def upper_profiles(points: np.ndarray, angles: np.ndarray, center: np.ndarray,
                   last_inner: np.ndarray, last_outer: np.ndarray,
                   rim: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    upper_zs = np.arange(280, TOP_GRID_MM+.01, 5.0)
    inner_rows, outer_rows, observed = [], [], []
    prev_inner = last_inner.copy()
    prev_outer = last_outer.copy()
    bearing = np.mod(np.arctan2(points[:, 1]-center[1], points[:, 0]-center[0]), 2*np.pi)
    radius = np.linalg.norm(points[:, :2]-center, axis=1)
    for z in upper_zs:
        band = np.abs(points[:, 2]-z) <= 4.0
        available = np.zeros(len(angles), bool)
        measured = prev_inner.copy()
        for i, a in enumerate(angles):
            if z > rim[i] + 3:
                continue
            m = band & (angular_distance(bearing, a) <= np.deg2rad(3.5))
            rr = radius[m]
            if len(rr) >= 12:
                available[i] = True
                measured[i] = max(prev_inner[i], float(np.quantile(rr, .98)) + 7.0)
        # Missing azimuths stay at the last observed profile; their status is
        # carried into validation and is never called an observed contour.
        smooth = gaussian_filter1d(measured, 1.5, mode="nearest")
        current_inner = np.maximum(prev_inner, smooth)
        current_outer = np.maximum(prev_outer, current_inner + 3.0)
        inner_rows.append(current_inner)
        outer_rows.append(current_outer)
        observed.append(available)
        prev_inner, prev_outer = current_inner, current_outer
    return upper_zs, np.asarray(inner_rows), np.asarray(outer_rows), np.asarray(observed)


def interpolate_rows(source_z: np.ndarray, source_rows: np.ndarray, target_z: np.ndarray) -> np.ndarray:
    return np.stack([np.interp(target_z, source_z, source_rows[:, i])
                     for i in range(source_rows.shape[1])], axis=1)


def active_cells(zs: np.ndarray, angles: np.ndarray, rim: np.ndarray) -> np.ndarray:
    mid_z = (zs[:-1]+zs[1:])/2
    mid_a = (angles[:-1]+angles[1:])/2
    rim_mid = (rim[:-1]+rim[1:])/2
    active = mid_z[:, None] <= rim_mid[None, :]
    distance = angular_distance(mid_a, np.deg2rad(BOLT_ANGLE_DEG))
    half = np.deg2rad(BOLT_NOTCH_HALF_ANGLE_DEG)
    notch_top = BOLT_NOTCH_TOP_MM - BOLT_NOTCH_ROUND_MM*(distance/half)**2
    notch = (distance[None, :] < half) & (mid_z[:, None] < notch_top[None, :])
    return active & ~notch


def build_mesh(zs: np.ndarray, angles: np.ndarray, center: np.ndarray,
               inner: np.ndarray, outer: np.ndarray, active: np.ndarray) -> trimesh.Trimesh:
    rows, cols = len(zs), len(angles)
    centers=np.broadcast_to(center,(rows,2)) if np.asarray(center).ndim==1 else np.asarray(center)
    vertices = []
    for kind in (inner, outer):
        vertices.extend(np.stack((centers[:,0,None] + kind*np.cos(angles)[None, :],
                                  centers[:,1,None] + kind*np.sin(angles)[None, :],
                                  np.broadcast_to(zs[:, None], kind.shape)), axis=-1).reshape(-1, 3))
    vertices = np.asarray(vertices)
    size = rows*cols
    faces = []
    def v(side, j, i):
        return side*size+j*cols+i
    def quad(a,b,c,d):
        faces.extend(((a,b,c),(a,c,d)))
    for j, i in np.argwhere(active):
        quad(v(0,j,i),v(0,j,i+1),v(0,j+1,i+1),v(0,j+1,i))
        quad(v(1,j,i+1),v(1,j,i),v(1,j+1,i),v(1,j+1,i+1))
        if j == 0 or not active[j-1,i]:
            quad(v(0,j,i+1),v(0,j,i),v(1,j,i),v(1,j,i+1))
        if j == active.shape[0]-1 or not active[j+1,i]:
            quad(v(0,j+1,i),v(0,j+1,i+1),v(1,j+1,i+1),v(1,j+1,i))
        if i == 0 or not active[j,i-1]:
            quad(v(0,j,i),v(0,j+1,i),v(1,j+1,i),v(1,j,i))
        if i == active.shape[1]-1 or not active[j,i+1]:
            quad(v(0,j+1,i+1),v(0,j,i+1),v(1,j,i+1),v(1,j+1,i+1))
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces), process=True)
    trimesh.repair.fix_normals(mesh)
    return mesh


def clearance_audit(points: np.ndarray, zs: np.ndarray, angles: np.ndarray,
                    center: np.ndarray, inner: np.ndarray, rim: np.ndarray) -> dict:
    sample = points[(points[:,2]>=BOTTOM_MM)&(points[:,2]<=rim.max())]
    if len(sample)>100000:
        sample=sample[np.random.default_rng(12).choice(len(sample),100000,replace=False)]
    t=np.mod(np.arctan2(sample[:,1]-center[1],sample[:,0]-center[0])-angles[0],2*np.pi)+angles[0]
    keep=t<=angles[-1]
    sample,t=sample[keep],t[keep]
    rim_at=np.interp(t,angles,rim)
    bolt=(angular_distance(t,np.pi)<np.deg2rad(BOLT_NOTCH_HALF_ANGLE_DEG))&(sample[:,2]<BOLT_NOTCH_TOP_MM)
    keep=(sample[:,2]<rim_at)&(~bolt)
    sample,t=sample[keep],t[keep]
    ji=np.clip(np.searchsorted(zs,sample[:,2])-1,0,len(zs)-2)
    ii=np.clip(np.searchsorted(angles,t)-1,0,len(angles)-2)
    a=(sample[:,2]-zs[ji])/(zs[ji+1]-zs[ji])
    b=(t-angles[ii])/(angles[ii+1]-angles[ii])
    r=(inner[ji,ii]*(1-a)*(1-b)+inner[ji+1,ii]*a*(1-b)
       +inner[ji,ii+1]*(1-a)*b+inner[ji+1,ii+1]*a*b)
    gap=r-np.linalg.norm(sample[:,:2]-center,axis=1)
    violations=sample[gap<0]
    return {"sample_count":int(len(gap)),"gap_p01_mm":round(float(np.quantile(gap,.01)),2),
            "gap_min_mm":round(float(gap.min()),2),
            "negative_radial_gaps":int(np.count_nonzero(gap<0)),
            "less_than_2mm_radial_gaps":int(np.count_nonzero(gap<2)),
            "negative_gap_z_mm":np.round(violations[:,2],2).tolist()}


def render_rim(rim: np.ndarray, angles: np.ndarray) -> None:
    im=Image.new("RGB",(1100,520),"white")
    d=ImageDraw.Draw(im)
    d.text((25,15),"Upper edge derived from point-cloud height by azimuth (mm)",fill="black")
    for h in (280,300,320,340,360):
        y=465-(h-275)*4
        d.line((80,y,1050,y),fill="#dddddd",width=1)
        d.text((20,y-8),str(h),fill="#666666")
    xy=[(80+(i/(len(angles)-1))*970,465-(h-275)*4) for i,h in enumerate(rim)]
    d.line(xy,fill="#087e99",width=4)
    d.text((80,485),"opening edge 122°",fill="black")
    d.text((895,485),"418° opening edge",fill="black")
    im.save(HERE/"upper_rim_evidence.png")


def main() -> None:
    HERE.mkdir(exist_ok=True)
    points=base.load_points(CONFIG)
    start=np.deg2rad(OPENING_CENTER_DEG+OPENING_DEG/2)
    angles=np.linspace(start,start+2*np.pi-np.deg2rad(OPENING_DEG),ANGLE_COUNT)
    low_z,centers,lower,reports=lower_profiles(points,angles)
    # Re-use the fitted central axis; the remaining center drift is small and
    # is retained in the lower profiles rather than adding a new tilted axis.
    center=centers[-1]
    shifted_inner=np.asarray([np.linalg.norm(np.column_stack((c[0]+r*np.cos(angles)-center[0],
                            c[1]+r*np.sin(angles)-center[1])),axis=1)
                            for c,r in zip(centers,lower[0])])
    shifted_outer=np.asarray([np.linalg.norm(np.column_stack((c[0]+r*np.cos(angles)-center[0],
                            c[1]+r*np.sin(angles)-center[1])),axis=1)
                            for c,r in zip(centers,lower[1])])
    rim,rim_counts=observed_upper_rim(points,angles,center)
    upper_z,upper_inner,upper_outer,upper_observed=upper_profiles(
        points,angles,center,shifted_inner[-1],shifted_outer[-1],rim)
    source_z=np.r_[low_z,upper_z]
    source_inner=np.vstack((shifted_inner,upper_inner))
    source_outer=np.vstack((shifted_outer,upper_outer))
    zs=np.arange(BOTTOM_MM,TOP_GRID_MM+.01,GRID_STEP_MM)
    inner=interpolate_rows(source_z,source_inner,zs)
    outer=interpolate_rows(source_z,source_outer,zs)
    active=active_cells(zs,angles,rim)
    mesh=build_mesh(zs,angles,center,inner,outer,active)
    mesh.export(HERE/"full_length_cover_concept.stl")
    mesh.export(HERE/"full_length_cover_concept.ply")
    base.ROOT=HERE
    base.STATIONS_MM=[BOTTOM_MM,float(rim.max())]
    base.render_mesh(mesh)
    render_rim(rim,angles)
    report={"status":"REJECTED SHAPE PROTOTYPE - MIDSECTION ROUGHNESS AND UPPER RIM UNDETERMINED",
            "geometry_z_bounds_mm":np.round(mesh.bounds[:,2],2).tolist(),
            "mesh_extents_mm":np.round(mesh.extents,2).tolist(),
            "mesh_watertight":bool(mesh.is_watertight),
            "mesh_components":len(mesh.split(only_watertight=False)),
            "mesh_volume_mm3":round(float(mesh.volume),1),
            "scan_height_envelope_mm":[round(float(rim.min()),1),round(float(rim.max()),1)],
            "upper_rim_min_angle_sample_points":int(rim_counts.min()),
            "bolt_notch":{"orientation_deg":BOLT_ANGLE_DEG,"angular_half_width_deg":BOLT_NOTCH_HALF_ANGLE_DEG,
                          "top_z_mm":BOLT_NOTCH_TOP_MM,"meaning":"provisional open relief, not a measured hole"},
            "upper_extension":"point-cloud rim height; radial profile uses sparse upper scan with carry-forward where missing",
            "scan_radial_audit":clearance_audit(points,zs,angles,center,inner,rim),
            "lower_station_reports":reports,
            "upper_observed_fraction_by_z":[{"z_mm":float(z),"fraction":round(float(row.mean()),3)}
                                             for z,row in zip(upper_z,upper_observed)]}
    (HERE/"validation.json").write_text(json.dumps(report,indent=2)+"\n")
    np.savez_compressed(HERE/"profile_data.npz",zs=zs,angles=angles,inner=inner,
                        outer=outer,rim=rim,active=active,center=center)
    print(json.dumps({k:v for k,v in report.items() if k not in ("lower_station_reports","upper_observed_fraction_by_z")},indent=2))


if __name__=="__main__":
    main()
