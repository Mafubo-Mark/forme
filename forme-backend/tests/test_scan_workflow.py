from pathlib import Path
import hashlib,json,pytest
from fastapi.testclient import TestClient
from forme_backend import scan_workflow as scan
from forme_backend.api import create_app
from forme_backend.config import Settings
from forme_backend.store import Store

@pytest.fixture
def current(tmp_path):
 data=tmp_path/'data';store=Store(data);store.create_session('session');store.create_upload('upload','source.mov','video/quicktime',5,'session');v=data/'uploads/upload/source.video';v.parent.mkdir(parents=True);v.write_bytes(b'video');store.transition('upload','initiated','uploaded',actual_bytes=5,sha256=scan.sha(v));store.transition('upload','uploaded','needs_capture_review');store.transition('upload','needs_capture_review','accepted');store.create_submission('sub','session','upload','blue','ABS','','06');store.create_model_job('model','sub');cloud=data/'model_jobs/model/dense/fused.ply';cloud.parent.mkdir(parents=True);cloud.write_bytes(b'raw cloud');model=data/'model_jobs/model/sparse/0';model.mkdir(parents=True)
 for n in ['cameras.bin','images.bin','points3D.bin']:(model/n).write_bytes(n.encode())
 store.transition_model_job('model','scale_review',status='needs_input',metrics={'colmapModel':'0'})
 folder=scan.root(data,'sub')/'scan_reference';folder.mkdir(parents=True);(folder/'subject_upright_mm.npz').write_bytes(b'input-array-placeholder-for-gate-tests')
 ruler={'sourceVideoSha256':scan.sha(v),'mmPerColmapUnit':1.,'knownTargetLengthMm':200,'quality':{'commonImages':4},'modelFilesSha256':{n:scan.sha(model/n) for n in ['cameras.bin','images.bin','points3D.bin']}};scan.write(folder/'ruler_calibration_extended.json',ruler)
 scan.write(folder/'geometry_review.json',{'sourceVideoSha256':scan.sha(v),'pointcloudSha256':scan.sha(folder/'subject_upright_mm.npz'),'rulerSha256':scan.sha(folder/'ruler_calibration_extended.json'),'targetDistanceAfterMm':200,'colmapToUprightMm':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]});scan.write(folder/'observed_upper_rim.json',[{'angle':a,'upperZP99_5':320} for a in range(-175,180,10)])
 for n in ['front.png','side.png','rim.png']:(folder/n).write_bytes(n.encode())
 recipe={'templateId':'06','centerXYMm':[0,24],'bottomZMm':-60,'rimExposureMm':20,'clearanceMm':2,'bolt':{'baseMm':[35,10,9],'axis':[1,0,0],'diameterMm':38}}
 scan.write(folder/'reference_review.json',{'sourceVideoSha256':scan.sha(v),'rawCloudSha256':scan.sha(cloud),'targetDistanceMm':200,'reviewNotes':'current camera overlays reviewed','files':{n:scan.sha(folder/n) for n in scan.FILES},'overlays':{n:scan.sha(folder/n) for n in ['front.png','side.png','rim.png']},'suggestedRecipe':recipe})
 return data,store,folder

CONFIRM={'targetLengthConfirmed':True,'geometryReviewed':True,'notes':'已核对当前标尺和三视图'}

def test_operator_auth_and_reference_gates(current):
 data,store,folder=current;client=TestClient(create_app(Settings(data,'secret','ffprobe','ffmpeg')));prefix='/api/internal/submissions/sub/scan-workflow';auth={'Authorization':'Bearer secret'}
 assert client.post(prefix+'/run').status_code==401
 assert client.post(prefix+'/run',headers=auth).json()['detail']['code']=='GEOMETRY_APPROVAL_REQUIRED'
 assert client.post(prefix+'/approve',headers=auth,json={'notes':'missing decisions'}).status_code==409
 assert client.post(prefix+'/approve',headers=auth,json=CONFIRM).status_code==200
 a=client.post(prefix+'/run',headers=auth).json();b=client.post(prefix+'/run',headers=auth).json();assert a['candidateId']==b['candidateId'];assert len(b['attempts'])==1
 assert client.post(prefix+'/approve',headers=auth,json=CONFIRM).status_code==409


def test_changed_input_and_camera_model_invalidate_approval(current):
 data,store,folder=current;scan.approve(data,'sub',store,CONFIRM);(folder/'subject_upright_mm.npz').write_bytes(b'changed')
 with pytest.raises(scan.ScanError,match='REFERENCE_FILE_CHANGED'):scan.enqueue(data,'sub',store)
 # Even if reference metadata is re-sealed, a different camera model cannot use this ruler.
 (folder/'subject_upright_mm.npz').write_bytes(b'input-array-placeholder-for-gate-tests');(data/'model_jobs/model/sparse/0/cameras.bin').write_bytes(b'changed camera')
 with pytest.raises(scan.ScanError,match='RULER_CAMERA_MODEL_CHANGED'):scan.approve(data,'sub',store,CONFIRM)


def test_new_route_has_no_hunyuan_dependency_and_stops_failed_runtime(current):
 data,store,folder=current;scan.approve(data,'sub',store,CONFIRM);scan.enqueue(data,'sub',store)
 assert scan.execute(data,'sub',store,'/missing/python','/missing/blender') is True
 state=scan.snapshot(data,'sub');assert state['status']=='failed';assert 'RUNTIME' in state['error'];assert scan.result_files(data,'sub') is None
 flow=scan.flow(data,'sub',store);assert flow['trialCandidate'] is None;assert all('hunyuan' not in s['id'] for s in flow['stages'])
 # A fresh review allows one retry, then the same approved config is exhausted.
 scan.approve(data,'sub',store,CONFIRM);scan.enqueue(data,'sub',store);scan.execute(data,'sub',store,'/missing/python','/missing/blender');scan.approve(data,'sub',store,CONFIRM)
 with pytest.raises(scan.ScanError,match='TWO_ATTEMPTS'):scan.enqueue(data,'sub',store)


def test_download_and_cloud_bridge_use_new_hash_bound_stl(current,monkeypatch):
 data,store,folder=current;scan.approve(data,'sub',store,CONFIRM);state=scan.enqueue(data,'sub',store);root=scan.root(data,'sub');out=root/'scan_candidates'/state['candidateId'];out.mkdir(parents=True)
 for n in ['cover_front.stl','cover_rear.stl','cover_trial_mm.stl']:(out/n).write_bytes(n.encode())
 (out/'stl_delivery.zip').write_bytes(b'zip delivery');scan.write(out/'delivery_sha256.json',{'stl_delivery.zip':scan.sha(out/'stl_delivery.zip')});scan.write(out/'release_review.json',{'status':'STL_CANDIDATE_READY','candidateId':out.name,'requiredBuildHeightMm':375.25,'files':{n:scan.sha(out/n) for n in ['cover_front.stl','cover_rear.stl','cover_trial_mm.stl']}})
 raw=scan.read(root/'scan_workflow.json');raw.update(status='ready',outputRelative=str(out.relative_to(root)),releaseReviewSha256=scan.sha(out/'release_review.json'));scan.write(root/'scan_workflow.json',raw)
 client=TestClient(create_app(Settings(data,'secret','ffprobe','ffmpeg')));headers={'Authorization':'Bearer secret'};prefix='/api/internal/submissions/sub'
 assert client.get(prefix+'/print-candidate/stl/front',headers=headers).content==b'cover_front.stl'
 assert client.get(prefix+'/print-candidate/package',headers=headers).content==b'zip delivery'
 from forme_backend.cloud_bridge import CloudBridge
 bridge=CloudBridge('https://example.invalid','k'*32,Settings(data,'secret','x','y'),store);calls=[];monkeypatch.setattr(bridge,'request',lambda *a,**kw:calls.append((a,kw)) or {});bridge.sync_job('sub',None);assert any(a[0]=='PUT' and kw['file']==out/'cover_trial_mm.stl' for a,kw in calls)
 (out/'cover_front.stl').write_bytes(b'tampered');assert scan.result_files(data,'sub') is None;assert client.get(prefix+'/print-candidate/stl/front',headers=headers).status_code!=200


def test_reference_geometry_and_recipe_cannot_mirror_or_erase_bolt_coverage(current):
 data,store,folder=current;ref=scan.reference(data,'sub',store)
 with pytest.raises(scan.ScanError,match='BELOW_BOLT'):scan.recipe(ref,{'bottomZMm':0})
 with pytest.raises(scan.ScanError,match='TEMPLATE'):scan.recipe(ref,{'templateId':'01'})
 geom=scan.read(folder/'geometry_review.json');geom['colmapToUprightMm'][0][0]=-1;scan.write(folder/'geometry_review.json',geom);review=scan.read(folder/'reference_review.json');review['files']['geometry_review.json']=scan.sha(folder/'geometry_review.json');scan.write(folder/'reference_review.json',review)
 with pytest.raises(scan.ScanError,match='MIRRORED'):scan.reference(data,'sub',store)
