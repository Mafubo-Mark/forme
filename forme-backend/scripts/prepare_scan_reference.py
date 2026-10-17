"""Seal a current-task crop, rigid frame, bolt recipe and camera overlays for review.
Run with geometry Python. This helper does not invent missing scale or orientations.
"""
from pathlib import Path
import argparse,json,sys,shutil
import numpy as np
from plyfile import PlyData
from scipy.spatial import cKDTree
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from forme_backend import scan_workflow as s
from forme_backend.store import Store

def main():
 p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--submission',required=True);p.add_argument('--crop-ply',type=Path,required=True);p.add_argument('--frame-json',type=Path,required=True);p.add_argument('--recipe-json',type=Path,required=True);p.add_argument('--overlay',type=Path,action='append',required=True);p.add_argument('--target-mm',type=float,required=True);p.add_argument('--notes',required=True);args=p.parse_args()
 data=args.data_dir.resolve();store=Store(data);sub=store.get_submission(args.submission);job=store.model_job_for_submission(args.submission)
 if not sub or not job or job['stage']!='scale_review':raise s.ScanError('CURRENT_RECONSTRUCTION_REQUIRED')
 folder=s.root(data,args.submission);ruler_path=folder/'ruler_calibration.json';ruler=s.read(ruler_path)
 if not ruler or ruler.get('sourceVideoSha256')!=sub['upload']['sha256']:raise s.ScanError('CURRENT_TASK_RULER_REQUIRED')
 frame=s.read(args.frame_json)
 if frame.get('sourceVideoSha256')!=sub['upload']['sha256']:raise s.ScanError('FRAME_VIDEO_MISMATCH')
 T=np.array(frame['colmapToUprightMm'],float);scale=float(ruler['mmPerColmapUnit'])
 if T.shape!=(4,4) or not np.isfinite(T).all() or not np.allclose(T[3],[0,0,0,1]) or not np.allclose((T[:3,:3]/scale).T@(T[:3,:3]/scale),np.eye(3),atol=1e-5) or np.linalg.det(T[:3,:3])<0:raise s.ScanError('INVALID_SCALED_RIGID_FRAME')
 raw_path=data/'model_jobs'/job['id']/'dense/fused.ply';raw=PlyData.read(raw_path)['vertex'].data;crop=PlyData.read(args.crop_ply)['vertex'].data;xyz=lambda v:np.column_stack([v[k] for k in ['x','y','z']]);points=xyz(crop)
 if len(points)<1000:raise s.ScanError('INSUFFICIENT_SUBJECT_POINTS')
 distance,_=cKDTree(xyz(raw)).query(points,k=1,workers=4)
 if distance.max()>1e-4:raise s.ScanError('CROP_NOT_SUBSET_OF_CURRENT_CLOUD')
 upright=points@T[:3,:3].T+T[:3,3];rgb=np.column_stack([crop[k] for k in ['red','green','blue']]);targets=np.array([ruler['targetAColmap'],ruler['targetBColmap']]);ab=targets@T[:3,:3].T+T[:3,3]
 if abs(np.linalg.norm(ab[1]-ab[0])-args.target_mm)>.05:raise s.ScanError('TARGET_LENGTH_MISMATCH')
 if len(args.overlay)<3:raise s.ScanError('THREE_CAMERA_REVIEW_OVERLAYS_REQUIRED')
 with s.lock(folder):
  state=s.read(folder/'scan_workflow.json',{})
  if state.get('status') in ['queued','running']:raise s.ScanError('SCAN_JOB_ACTIVE')
  dest=folder/'scan_reference'
  if dest.exists():raise s.ScanError('REFERENCE_ALREADY_EXISTS_ARCHIVE_EXPLICITLY_BEFORE_REVISION')
  dest.mkdir();np.savez(dest/'subject_upright_mm.npz',xyz=upright,rgb=rgb);shutil.copy2(ruler_path,dest/'ruler_calibration_extended.json')
  angle=np.arctan2(upright[:,1]-24,upright[:,0]);rows=[]
  for deg in range(-175,180,10):
   mask=abs(np.arctan2(np.sin(angle-np.radians(deg)),np.cos(angle-np.radians(deg))))<=np.pi/36;pts=upright[mask]
   if len(pts)<100:raise s.ScanError('UPPER_RIM_SECTOR_INCOMPLETE')
   rows.append({'angle':deg,'points':len(pts),'upperZP99_5':float(np.quantile(pts[:,2],.995))})
  s.write(dest/'observed_upper_rim.json',rows)
  geometry={'sourceVideoSha256':sub['upload']['sha256'],'colmapToUprightMm':T.tolist(),'pointcloudSha256':s.sha(dest/'subject_upright_mm.npz'),'rulerSha256':s.sha(dest/'ruler_calibration_extended.json'),'targetDistanceAfterMm':float(np.linalg.norm(ab[1]-ab[0])),'rawCloudSha256':s.sha(raw_path),'cropSha256':s.sha(args.crop_ply),'subjectPoints':len(points),'scope':'agent-proposed crop and rigid frame; operator must review current camera overlays before approval'}
  s.write(dest/'geometry_review.json',geometry);overlays={}
  for i,path in enumerate(args.overlay):
   if path.suffix.lower() not in ['.jpg','.jpeg','.png']:raise s.ScanError('OVERLAY_MUST_BE_IMAGE')
   name=f'review_{i+1}{path.suffix.lower()}';shutil.copy2(path,dest/name);overlays[name]=s.sha(dest/name)
  s.write(dest/'reference_review.json',{'sourceVideoSha256':sub['upload']['sha256'],'rawCloudSha256':s.sha(raw_path),'targetDistanceMm':args.target_mm,'reviewNotes':args.notes,'files':{n:s.sha(dest/n) for n in s.FILES},'overlays':overlays,'suggestedRecipe':s.read(args.recipe_json)})
  # Preparation invalidates any older approval and never marks the new scan accepted.
  s.write(folder/'scan_workflow.json',{'status':'awaiting_reference','stage':'geometry_review','method':s.METHOD,'attempts':state.get('attempts',[])})
 print(json.dumps(s.snapshot(data,args.submission),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
