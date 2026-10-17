"""Prepare test4's calibrated COLMAP poses and subject alpha images for Brush 3DGS."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import cv2
import numpy as np
import pycolmap
from plyfile import PlyData, PlyElement
from PIL import Image, ImageDraw

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
BASE = ROOT / 'gs-experiment'
DATA = BASE / 'dataset-alpha'
RECON = ROOT / 'reconstruction/dense/sparse'
FRAMES = ROOT / 'reconstruction/dense/images'
CLOUD = ROOT / 'analysis/isolated-prosthesis.ply'


def foreground_mask(points: np.ndarray, im, cam) -> np.ndarray:
    # Rendering the already isolated dense cloud into each registered camera
    # supplies a subject silhouette without a separate AI segmenter.
    h, w = cam.height // 2, cam.width // 2
    xyz = points @ np.asarray(im.cam_from_world().matrix())[:, :3].T
    xyz += np.asarray(im.cam_from_world().matrix())[:, 3]
    good = xyz[:, 2] > 0
    xyz = xyz[good]
    fx, fy, cx, cy = np.asarray(cam.params)[:4] / 2
    u = np.round(fx * xyz[:, 0] / xyz[:, 2] + cx).astype(np.int32)
    v = np.round(fy * xyz[:, 1] / xyz[:, 2] + cy).astype(np.int32)
    good = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    seed = np.zeros((h,w), np.uint8)
    seed[v[good],u[good]] = 255
    seed = cv2.dilate(seed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(11,11)))
    seed = cv2.morphologyEx(seed,cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(31,31)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(seed,8)
    if count < 2:
        raise RuntimeError(f'No projected subject points in {im.name}')
    largest = 1 + np.argmax(stats[1:,cv2.CC_STAT_AREA])
    seed = (labels == largest).astype(np.uint8)*255
    contours,_ = cv2.findContours(seed,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(seed,contours,-1,255,cv2.FILLED)
    # Loose alpha avoids cutting away sparse outer shell points; the subject
    # still needs a visual mask review before it is used to infer a CAD surface.
    seed = cv2.dilate(seed,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9)))
    return cv2.resize(seed,(cam.width,cam.height),interpolation=cv2.INTER_LINEAR)


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--review-only',action='store_true')
    args=parser.parse_args()
    rec=pycolmap.Reconstruction(str(RECON))
    ply=PlyData.read(str(CLOUD))['vertex'].data
    points=np.column_stack([ply[k] for k in ('x','y','z')]).astype(np.float64)
    names=sorted(rec.images[i].name for i in rec.reg_image_ids())
    selected=names[::max(1,len(names)//8)] if args.review_only else names
    review=[]
    (BASE/'mask-review').mkdir(parents=True,exist_ok=True)
    if not args.review_only:
        (DATA/'images').mkdir(parents=True,exist_ok=True)
        (DATA/'sparse/0').mkdir(parents=True,exist_ok=True)
    masks={}
    for name in selected:
        im=rec.find_image_with_name(name)
        cam=rec.cameras[im.camera_id]
        rgb=cv2.imread(str(FRAMES/name))
        if rgb is None:
            raise FileNotFoundError(name)
        alpha=foreground_mask(points,im,cam)
        masks[name]=alpha
        if not args.review_only:
            bgra=np.dstack((rgb,alpha))
            cv2.imwrite(str(DATA/'images'/(Path(name).stem+'.png')),bgra,
                        [cv2.IMWRITE_PNG_COMPRESSION,3])
        if len(review)<9:
            shown=rgb.copy()
            edge,_=cv2.findContours((alpha>127).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(shown,edge,-1,(0,255,255),6)
            tile=cv2.resize(shown,(270,480),interpolation=cv2.INTER_AREA)
            review.append((name,tile))
        print(name,'mask fraction',round(float(np.mean(alpha>127)),3),flush=True)
    sheet=Image.new('RGB',(3*270,3*510),(27,31,35))
    draw=ImageDraw.Draw(sheet)
    for i,(name,tile) in enumerate(review):
        x,y=i%3*270,i//3*510
        sheet.paste(Image.fromarray(cv2.cvtColor(tile,cv2.COLOR_BGR2RGB)),(x,y+25))
        draw.text((x+5,y+5),name,fill='white')
    sheet.save(BASE/'mask-review/montage.jpg',quality=90)
    if args.review_only:
        return
    rec.write_text(str(DATA/'sparse/0'))
    image_txt=DATA/'sparse/0/images.txt'
    image_txt.write_text(re.sub(r'frame_(\d+)\.jpg',r'frame_\1.png',image_txt.read_text()))
    # A bounded, subject-only initialization keeps the GPU training affordable.
    rng=np.random.default_rng(41)
    chosen=rng.choice(len(ply),min(20000,len(ply)),replace=False)
    init=np.empty(len(chosen),dtype=[('x','f4'),('y','f4'),('z','f4'),
                                     ('red','u1'),('green','u1'),('blue','u1')])
    for field in init.dtype.names:
        init[field]=ply[field][chosen]
    PlyData([PlyElement.describe(init,'vertex')],text=False).write(str(DATA/'init.ply'))
    print('prepared',len(names),'registered alpha frames, init points',len(init),flush=True)


if __name__=='__main__':
    main()
