"""Fit low-frequency body profiles to the independent photo-native visual hull."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter1d
from scipy.spatial import ConvexHull

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT/'pointcloud-contour-prototype'))
import build_partial_shell as base

cfg=json.loads((ROOT/'pointcloud-axis-corrected/sections.json').read_text())
data=np.load(ROOT/'independent-silhouette/photo_native_hull_volume.npz')
ids=np.argwhere(data['support'])
local=np.column_stack((data['x_mm'][ids[:,2]],data['y_mm'][ids[:,1]],data['z_mm'][ids[:,0]]))
world=data['origin_colmap']+local@data['axes_colmap']/cfg['input_to_mm_scale']
frame=np.asarray([cfg['x_in_input_coordinates'],cfg['front_in_input_coordinates'],
                  cfg['axis_in_input_coordinates']]).T
hull=(world-np.asarray(cfg['origin_in_input_coordinates']))@frame*cfg['input_to_mm_scale']
hull[:,2]-=cfg['trim_low_input_coordinate']*cfg['input_to_mm_scale']+cfg['cover_start_mm']
scan=base.load_points(cfg)
old=np.load(ROOT/'pointcloud-full-cover-prototype/profile_data.npz')


def cross(a,b):
    return a[...,0]*b[...,1]-a[...,1]*b[...,0]


def ray_polygon(polygon: np.ndarray, center: np.ndarray, angles: np.ndarray) -> np.ndarray:
    p=polygon-center
    e=np.roll(p,-1,axis=0)-p
    d=np.column_stack((np.cos(angles),np.sin(angles)))
    den=cross(d[:,None,:],e[None,:,:])
    safe=np.where(abs(den)<1e-9,np.nan,den)
    t=cross(p[None,:,:],e[None,:,:])/safe
    u=cross(p[None,:,:],d[:,None,:])/safe
    valid=(t>0)&(u>=-1e-8)&(u<=1+1e-8)
    values=np.where(valid,t,np.nan)
    r=np.nanmax(values,axis=1)
    if np.any(~np.isfinite(r)):
        raise ValueError('Ray missed visual-hull polygon; center may be outside')
    return r


def area_centroid(poly: np.ndarray) -> np.ndarray:
    nxt=np.roll(poly,-1,axis=0)
    k=cross(poly,nxt)
    area=k.sum()/2
    return np.sum((poly+nxt)*k[:,None],axis=0)/(6*area)


def build() -> None:
    HERE.mkdir(exist_ok=True)
    zs=np.arange(20,276,5,dtype=float)
    theta=np.linspace(0,2*np.pi,360,endpoint=False)
    centers=[]; radii=[]; metadata=[]
    for z in zs:
        band=hull[np.abs(hull[:,2]-z)<=4.5,:2]
        if len(band)<40:
            raise ValueError(f'Insufficient visual hull at z={z}: {len(band)} voxels')
        indices=ConvexHull(band).vertices
        polygon=band[indices]
        center=area_centroid(polygon)
        raw=ray_polygon(polygon,center,theta)
        # A 10-harmonic periodic Fourier curve retains the observed noncircular
        # body profile while discarding voxel stair steps and point spikes.
        coefficients=np.fft.rfft(raw)
        coefficients[11:]=0
        smooth=np.fft.irfft(coefficients,n=len(raw))
        centers.append(center);radii.append(smooth)
        metadata.append({'z_mm':z,'photo_hull_voxels_in_9mm_band':len(band),
                         'raw_radius_min_max_mm':np.round([raw.min(),raw.max()],2).tolist()})
    centers=gaussian_filter1d(np.asarray(centers),2.0,axis=0,mode='nearest')
    radii=gaussian_filter1d(np.asarray(radii),2.0,axis=0,mode='nearest')
    # The independent silhouette is a 3 mm diagnostic grid; 5 mm is a design
    # stand-off for the concept, not a proven physical fitting tolerance.
    inner=radii+5.0
    outer=inner+3.0
    np.savez_compressed(HERE/'green_profiles.npz',z_mm=zs,angles_rad=theta,
                        center_xy_mm=centers,object_radius_mm=radii,
                        inner_radius_mm=inner,outer_radius_mm=outer)
    (HERE/'profile_report.json').write_text(json.dumps({
        'status':'PHOTO-HULL-CONSTRAINED BODY PROFILES; 3MM INPUT GRID; NOT FIT VERIFIED',
        'z_range_mm':[float(zs[0]),float(zs[-1])],
        'section_step_mm':5,'fourier_harmonics':10,'design_standoff_mm':5,
        'wall_mm':3,'sections':metadata},indent=2)+'\n')
    levels=[50,100,150,200,250,275]
    im=Image.new('RGB',(1400,470*len(levels)),'white')
    draw=ImageDraw.Draw(im)
    for row,z in enumerate(levels):
        i=int(np.argmin(abs(zs-z)));center=centers[i]
        cx,cy,s=310,470*row+240,3.0
        cvt=lambda p:(cx+p[0]*s,cy-p[1]*s)
        draw.text((12,470*row+12),f'z={z} mm  grey: scan  green: photo hull  blue: smooth body  orange: new inner  red: rejected inner',fill='black')
        band=scan[np.abs(scan[:,2]-z)<4,:2]
        if len(band)>3000:
            band=band[np.random.default_rng(z).choice(len(band),3000,replace=False)]
        for p in band:
            x,y=cvt(p);draw.ellipse((x-1,y-1,x+1,y+1),fill='#aaaaaa')
        hb=hull[np.abs(hull[:,2]-z)<4.5,:2]
        poly=hb[ConvexHull(hb).vertices]
        coords=[cvt(p) for p in poly]
        draw.line(coords+coords[:1],fill='#16845b',width=3)
        for name,color in (('object','#206ab6'),('inner','#cf741e')):
            rr=radii[i] if name=='object' else inner[i]
            pts=[cvt(center+r*np.array([np.cos(a),np.sin(a)])) for r,a in zip(rr,theta)]
            draw.line(pts+pts[:1],fill=color,width=3)
        old_index=int(np.argmin(abs(old['zs']-z)))
        old_points=[cvt(old['center']+r*np.array([np.cos(a),np.sin(a)]))
                    for r,a in zip(old['inner'][old_index],old['angles'])]
        draw.line(old_points,fill='#ca3f44',width=2)
        draw.text((680,470*row+100),f'photo hull voxels: {len(hb)}',fill='#333333')
        draw.text((680,470*row+130),f'smooth profile radius: {radii[i].min():.1f}–{radii[i].max():.1f} mm',fill='#333333')
    im.save(HERE/'body_profile_comparison.png')
    print('Built',HERE/'green_profiles.npz')


if __name__=='__main__':
    build()
