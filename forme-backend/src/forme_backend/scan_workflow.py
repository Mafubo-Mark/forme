"""Durable, local scan-first cover jobs. Scientific review is bound to exact inputs."""
from __future__ import annotations
import contextlib,fcntl,hashlib,json,math,os,re,subprocess,time,uuid
from pathlib import Path
from .store import Store

BACKEND=Path(__file__).resolve().parents[2]
PROJECT=BACKEND.parent
METHOD='scanfit-v5-20261017'
FILES=('subject_upright_mm.npz','geometry_review.json','ruler_calibration_extended.json','observed_upper_rim.json')

class ScanError(ValueError): pass

def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def read(p:Path,default=None):return json.loads(p.read_text()) if p.is_file() else default

def write(p:Path,value):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,p)

def root(data:Path,sid:str)->Path:
 if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',sid):raise ScanError('INVALID_SUBMISSION_ID')
 return data/'cover_tasks'/sid

@contextlib.contextmanager
def lock(folder:Path):
 folder.mkdir(parents=True,exist_ok=True)
 with (folder/'scan_workflow.lock').open('a+') as f:
  fcntl.flock(f,fcntl.LOCK_EX)
  yield

def finite(value,lo,hi,name):
 if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not lo<=value<=hi:raise ScanError('INVALID_'+name)
 return float(value)

def reference(data:Path,sid:str,store:Store)->dict:
 sub=store.get_submission(sid)
 if not sub:raise ScanError('SUBMISSION_NOT_FOUND')
 if sub['upload']['status']!='accepted':raise ScanError('CAPTURE_REVIEW_REQUIRED')
 job=store.model_job_for_submission(sid)
 if not job or job['stage']!='scale_review':raise ScanError('COLMAP_RECONSTRUCTION_REQUIRED')
 cloud=data/'model_jobs'/job['id']/'dense/fused.ply';video=data/'uploads'/sub['upload_id']/'source.video'
 if not cloud.is_file() or not video.is_file():raise ScanError('SOURCE_FILES_MISSING')
 if sha(video)!=sub['upload']['sha256']:raise ScanError('SOURCE_VIDEO_HASH_MISMATCH')
 folder=root(data,sid)/'scan_reference';review=read(folder/'reference_review.json')
 if not review:raise ScanError('AGENT_REFERENCE_PREPARATION_REQUIRED')
 if review.get('sourceVideoSha256')!=sub['upload']['sha256'] or review.get('rawCloudSha256')!=sha(cloud):raise ScanError('REFERENCE_SOURCE_MISMATCH')
 if not review.get('reviewNotes') or not isinstance(review.get('files'),dict):raise ScanError('REFERENCE_REVIEW_NOTES_REQUIRED')
 for name in FILES:
  p=(folder/name).resolve()
  if not p.is_relative_to(folder.resolve()) or not p.is_file() or review['files'].get(name)!=sha(p):raise ScanError('REFERENCE_FILE_CHANGED:'+name)
 geometry=read(folder/'geometry_review.json');ruler=read(folder/'ruler_calibration_extended.json')
 if geometry.get('sourceVideoSha256')!=sub['upload']['sha256'] or geometry.get('pointcloudSha256')!=review['files']['subject_upright_mm.npz'] or geometry.get('rulerSha256')!=review['files']['ruler_calibration_extended.json']:raise ScanError('GEOMETRY_PROVENANCE_MISMATCH')
 matrix=geometry.get('colmapToUprightMm');scale=finite(ruler.get('mmPerColmapUnit'),.0001,1e7,'SCALE')
 if not isinstance(matrix,list) or len(matrix)!=4 or any(not isinstance(row,list) or len(row)!=4 for row in matrix):raise ScanError('INVALID_FRAME')
 if matrix[3]!=[0,0,0,1]:raise ScanError('INVALID_FRAME')
 cols=[[finite(matrix[r][c],-1e9,1e9,'FRAME')/scale for r in range(3)] for c in range(3)]
 for i in range(3):
  for j in range(3):
   if abs(sum(cols[i][k]*cols[j][k] for k in range(3))-(1 if i==j else 0))>1e-5:raise ScanError('FRAME_NOT_RIGID_UNIFORM_SCALE')
 a,b,c=cols;det=a[0]*(b[1]*c[2]-b[2]*c[1])-b[0]*(a[1]*c[2]-a[2]*c[1])+c[0]*(a[1]*b[2]-a[2]*b[1])
 if det<.99999:raise ScanError('MIRRORED_FRAME')
 known=finite(review.get('targetDistanceMm'),20,1000,'TARGET_DISTANCE')
 if abs(geometry.get('targetDistanceAfterMm',-1)-known)>.05:raise ScanError('RULER_LENGTH_MISMATCH')
 # Bind the ruler to the actual registered camera model of this job, not just video.
 model_name=(job.get('metrics') or {}).get('colmapModel')
 if not model_name:raise ScanError('CURRENT_CAMERA_MODEL_REQUIRED')
 model_root=data/'model_jobs'/job['id'];model_dir=(model_root/'sparse'/model_name).resolve()
 if not model_dir.is_relative_to(model_root.resolve()):raise ScanError('INVALID_CAMERA_MODEL_PATH')
 for name in ['cameras.bin','images.bin','points3D.bin']:
  if not (model_dir/name).is_file() or ruler.get('modelFilesSha256',{}).get(name)!=sha(model_dir/name):raise ScanError('RULER_CAMERA_MODEL_CHANGED')
 if abs(float(ruler.get('knownTargetLengthMm',-1))-known)>.01:raise ScanError('RULER_KNOWN_LENGTH_CHANGED')
 quality=ruler.get('quality',{})
 if quality.get('commonImages',0)<3:raise ScanError('RULER_THREE_VIEWS_REQUIRED')
 if ruler.get('sourceVideoSha256') and ruler['sourceVideoSha256']!=sub['upload']['sha256']:raise ScanError('RULER_VIDEO_MISMATCH')
 rows=read(folder/'observed_upper_rim.json')
 if not isinstance(rows,list) or len(rows)!=36:raise ScanError('RIM_36_SECTORS_REQUIRED')
 for i,row in enumerate(rows):
  if row.get('angle')!=-175+i*10:raise ScanError('RIM_ANGLE_ORDER_INVALID')
  finite(row.get('upperZP99_5'),100,500,'RIM_HEIGHT')
 overlays=review.get('overlays',{})
 if len(overlays)<3:raise ScanError('THREE_REVIEW_OVERLAYS_REQUIRED')
 for name,digest in overlays.items():
  p=(folder/name).resolve()
  if not p.is_relative_to(folder.resolve()) or not p.is_file() or sha(p)!=digest:raise ScanError('REVIEW_OVERLAY_CHANGED')
 return {'referenceRoot':str(folder),'sourceVideoSha256':sub['upload']['sha256'],'rawCloudSha256':review['rawCloudSha256'],'referenceReviewSha256':sha(folder/'reference_review.json'),'referenceFiles':review['files'],'review':review}

def recipe(ref:dict,overrides:dict)->dict:
 if not isinstance(overrides,dict):raise ScanError('RECIPE_MUST_BE_OBJECT')
 cfg=dict(ref['review'].get('suggestedRecipe',{}));cfg.update(overrides)
 if cfg.get('templateId')!='06':raise ScanError('ONLY_VALIDATED_TEMPLATE_06_SUPPORTED')
 bottom=finite(cfg.get('bottomZMm'),-120,0,'BOTTOM_Z')
 if bottom%10!=0:raise ScanError('BOTTOM_Z_REQUIRES_10MM_GRID')
 if cfg.get('centerXYMm')!=[0,24]:raise ScanError('REFERENCE_CENTER_MUST_BE_0_24')
 bolt=cfg.get('bolt',{})
 if not isinstance(bolt,dict):raise ScanError('BOLT_MUST_BE_OBJECT')
 base=bolt.get('baseMm');axis=bolt.get('axis')
 if not isinstance(base,list) or len(base)!=3 or not isinstance(axis,list) or len(axis)!=3:raise ScanError('BOLT_BASE_AXIS_REQUIRED')
 base=[finite(x,-400,400,'BOLT_BASE') for x in base];axis=[finite(x,-1,1,'BOLT_AXIS') for x in axis]
 if abs(sum(x*x for x in axis)-1)>.0001:raise ScanError('BOLT_AXIS_NOT_NORMALIZED')
 diameter=finite(bolt.get('diameterMm'),12,70,'BOLT_DIAMETER')
 if base[2]-diameter/2-bottom<10:raise ScanError('INSUFFICIENT_COVER_BELOW_BOLT')
 cfg={'method':METHOD,'templateId':'06','centerXYMm':[0,24],'bottomZMm':bottom,'transitionZMm':100.,'rimExposureMm':finite(cfg.get('rimExposureMm',20),5,40,'RIM_EXPOSURE'),'clearanceMm':finite(cfg.get('clearanceMm',2),1,8,'CLEARANCE'),'bolt':{'baseMm':base,'axis':axis,'diameterMm':diameter}}
 cfg.update({k:ref[k] for k in ['referenceRoot','sourceVideoSha256','rawCloudSha256','referenceReviewSha256','referenceFiles']})
 registry=read(PROJECT/'work-buddy-handoff/production-bases/06/manifest.json')
 if not registry:raise ScanError('TEMPLATE_BASE_NOT_INSTALLED')
 for side,digest in registry['sha256'].items():
  if sha(PROJECT/f'work-buddy-handoff/production-bases/06/{side}.stl')!=digest:raise ScanError('TEMPLATE_BASE_CHANGED')
 cfg['baseHashes']=registry['sha256'];return cfg

def snapshot(data:Path,sid:str)->dict:
 folder=root(data,sid);state=read(folder/'scan_workflow.json',{'status':'not_started'})
 ref=read(folder/'scan_reference/reference_review.json',{})
 return {**state,'method':METHOD,'referencePrepared':bool(ref),'suggestedRecipe':ref.get('suggestedRecipe'),'reviewNotes':ref.get('reviewNotes'),'targetDistanceMm':ref.get('targetDistanceMm'),'referenceFiles':list(FILES),'previewUrls':[f'/api/internal/submissions/{sid}/scan-workflow/reference/{name}' for name in ref.get('overlays',{}) if '/' not in name and '..' not in name], 'agentAction':'prepare current-video scale, crop, upright frame, rim and bolt evidence in scan_reference; see skill forme-scan-workflow','hunyuanRequired':False}

def approve(data:Path,sid:str,store:Store,payload:dict)->dict:
 folder=root(data,sid)
 with lock(folder):
  state=read(folder/'scan_workflow.json',{})
  if state.get('status') in ['running','queued']:raise ScanError('SCAN_JOB_ACTIVE')
  if payload.get('targetLengthConfirmed') is not True or payload.get('geometryReviewed') is not True:raise ScanError('LENGTH_AND_GEOMETRY_CONFIRMATION_REQUIRED')
  notes=payload.get('notes','')
  if not isinstance(notes,str) or len(notes.strip())<5:raise ScanError('REVIEW_NOTES_REQUIRED')
  ref=reference(data,sid,store);cfg=recipe(ref,payload.get('recipe',{}));cfg['approvalNotes']=notes
  signature=hashlib.sha256(json.dumps({k:v for k,v in cfg.items() if k!='approvalNotes'},sort_keys=True).encode()).hexdigest()
  state={'status':'approved','config':cfg,'configSha256':signature,'approvedAt':time.time(),'attempts':state.get('attempts',[]),'physicalFitVerified':False,'manufacturingApproved':False}
  write(folder/'scan_workflow.json',state)
 return snapshot(data,sid)

def enqueue(data:Path,sid:str,store:Store)->dict:
 folder=root(data,sid)
 with lock(folder):
  state=read(folder/'scan_workflow.json',{})
  if state.get('status') in ['queued','running','ready']:return snapshot(data,sid)
  if state.get('status')!='approved':raise ScanError('GEOMETRY_APPROVAL_REQUIRED')
  ref=reference(data,sid,store)
  if ref['referenceReviewSha256']!=state['config']['referenceReviewSha256']:raise ScanError('APPROVAL_STALE')
  if sum(a['configSha256']==state['configSha256'] for a in state['attempts'])>=2:raise ScanError('TWO_ATTEMPTS_EXHAUSTED_REVIEW_INPUTS')
  cid='scan-'+uuid.uuid4().hex[:12];state.update(status='queued',candidateId=cid,stage='queued',error=None);state['attempts'].append({'candidateId':cid,'configSha256':state['configSha256'],'queuedAt':time.time()});write(folder/'scan_workflow.json',state)
 return snapshot(data,sid)

def execute(data:Path,sid:str,store:Store,geometry_python:str,blender:str)->bool:
 folder=root(data,sid)
 with lock(folder):
  state=read(folder/'scan_workflow.json',{})
  if state.get('status')!='queued':return False
  state.update(status='running',startedAt=time.time(),stage='validate');write(folder/'scan_workflow.json',state)
 cid=state['candidateId'];out=folder/'scan_candidates'/cid
 def update(**values):
  state.update(values);write(folder/'scan_workflow.json',state)
 try:
  ref=reference(data,sid,store)
  if ref['referenceReviewSha256']!=state['config']['referenceReviewSha256']:raise ScanError('APPROVAL_STALE')
  current=recipe(ref,state['config'])
  if current['baseHashes']!=state['config']['baseHashes']:raise ScanError('TEMPLATE_APPROVAL_STALE')
  if not Path(geometry_python).is_file() or not Path(blender).is_file():raise ScanError('GEOMETRY_RUNTIME_MISSING')
  out.mkdir(parents=True,exist_ok=False);write(out/'run_config.json',state['config'])
  command=[geometry_python,str(BACKEND/'scripts/scanfit/run.py'),str(out),'--blender',blender]
  update(stage='fit_and_review')
  with (out/'worker.log').open('w') as log:
   result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=3600,check=False)
  if result.returncode:raise ScanError('GEOMETRY_FAILED_SEE_WORKER_LOG')
  # Inputs are rechecked after the long computation as well as before it.
  after=reference(data,sid,store)
  if after['referenceReviewSha256']!=ref['referenceReviewSha256']:raise ScanError('INPUTS_CHANGED_DURING_BUILD')
  report=read(out/'release_review.json')
  if not report or report.get('status')!='STL_CANDIDATE_READY':raise ScanError('FINAL_REVIEW_REQUIRED')
  update(stage='ready',status='ready',finishedAt=time.time(),outputRelative=str(out.relative_to(folder)),releaseReviewSha256=sha(out/'release_review.json'))
 except Exception as exc:
  update(status='failed',stage='stopped',error=str(exc)[:250],finishedAt=time.time())
 return True

def result_files(data:Path,sid:str)->tuple[Path,dict]|None:
 folder=root(data,sid);state=read(folder/'scan_workflow.json',{})
 if state.get('status')!='ready':return None
 try:
  ref=reference(data,sid,Store(data))
  if ref['referenceReviewSha256']!=state['config']['referenceReviewSha256']:return None
 except (ScanError,OSError,ValueError,KeyError,TypeError):return None
 out=(folder/state.get('outputRelative','')).resolve()
 if not out.is_relative_to((folder/'scan_candidates').resolve()):return None
 report=read(out/'release_review.json')
 if not report or report.get('status')!='STL_CANDIDATE_READY' or report.get('candidateId')!=out.name or sha(out/'release_review.json')!=state.get('releaseReviewSha256'):return None
 for name,digest in report.get('files',{}).items():
  p=(out/name).resolve()
  if not p.is_relative_to(out) or not p.is_file() or sha(p)!=digest:return None
 return out,report

def record_fit(data:Path,sid:str,payload:dict)->dict:
 found=result_files(data,sid)
 if not found:raise ScanError('READY_CANDIDATE_REQUIRED')
 out,report=found
 if payload.get('fitConfirmed') is not True or len(str(payload.get('notes','')).strip())<5:raise ScanError('FIT_CONFIRMATION_AND_NOTES_REQUIRED')
 record={'candidateId':out.name,'partsSha256':{s:report['files'][f'cover_{s}.stl'] for s in ['front','rear']},'userReportedFit':True,'notes':payload['notes'],'recordedAt':time.time(),'manufacturingApproved':False}
 write(out/'physical_fit_feedback.json',record);return record

def flow(data:Path,sid:str,store:Store)->dict|None:
 state=snapshot(data,sid)
 if state['status']=='not_started':return None
 sub=store.get_submission(sid);model=store.model_job_for_submission(sid);found=result_files(data,sid)
 trial=None
 if state['status']=='ready' and not found:
  state={**state,'status':'failed','error':'PUBLISHED_INPUT_OR_RESULT_CHANGED_REVIEW_REQUIRED'}
 if found:
  out,report=found;prefix=f'/api/internal/submissions/{sid}/print-candidate'
  trial={'candidateId':out.name,'deliveryFormat':'stl_zip','packageUrl':prefix+'/package','stlUrl':prefix+'/stl/combined','stlSha256':report['files']['cover_trial_mm.stl'],'frontStlUrl':prefix+'/stl/front','rearStlUrl':prefix+'/stl/rear','requiredBuildHeightMm':report['requiredBuildHeightMm'],'slicerVerified':False,'physicalFitVerified':False}
  feedback=read(out/'physical_fit_feedback.json')
  if feedback and feedback.get('partsSha256')=={s:report['files'][f'cover_{s}.stl'] for s in ['front','rear']}:trial['userReportedFit']=feedback.get('userReportedFit') is True
 stages=[{'id':'capture','label':'拍摄与已知标尺确认','state':'done' if sub['upload']['status']=='accepted' else 'review','detail':sub['upload']['status']},{'id':'colmap','label':'自动重建点云','state':'done' if model and model['stage']=='scale_review' else 'waiting','detail':model['stage'] if model else 'not_started'},{'id':'geometry','label':'尺度、轴线、上缘与螺栓复核','state':'done' if state['status'] in ['approved','queued','running','ready'] else 'review','detail':state['status']},{'id':'print_trial','label':'点云适配、开孔与 STL 打包','state':'review' if trial else 'waiting','detail':state.get('stage',state['status'])}]
 return {'submissionId':sid,'method':METHOD,'stages':stages,'nextStage':next((s['id'] for s in stages if s['state']!='done'),'print_trial'),'trialCandidate':trial,'rulerCalibration':None,'conceptBuildAllowed':False,'manufacturingApproved':False,'blockers':[state['error']] if state.get('error') else [],'scanWorkflow':state}
