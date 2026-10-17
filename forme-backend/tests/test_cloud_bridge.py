import hashlib
from pathlib import Path
from unittest.mock import patch

from forme_backend.cloud_bridge import CloudBridge
from forme_backend.config import Settings
from forme_backend.store import Store


def test_bridge_import_is_idempotent_and_preserves_local_review(tmp_path):
    video=b'\x00\x00\x00\x18ftypmp42'+b'0'*100
    sha=hashlib.sha256(video).hexdigest()
    sid='a'*32
    upload_id='b'*32
    job=dict(schemaVersion=1,submissionId=sid,uploadId=upload_id,filename='test.mp4',contentType='video/mp4',
             byteSize=len(video),sha256=sha,templateId='04',color='#123456',
             material='Durable Nylon',inspiration='test')
    settings=Settings(data_dir=tmp_path,dev_token='local-token',ffprobe='ffprobe',ffmpeg='ffmpeg')
    store=Store(tmp_path)
    bridge=CloudBridge('https://example.test','k'*48,settings,store)
    calls=[]

    def request(method,path,payload=None,**kwargs):
        calls.append((method,path,payload))
        return {'ok':True}

    def download(_job):
        path=tmp_path/'uploads'/upload_id/'source.video'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(video)
        return path

    def validate(local_store,_settings,claimed):
        local_store.transition(claimed['id'],'validating','needs_capture_review',
                               metadata_json='{"duration_seconds": 20}')

    bridge.request=request
    bridge.download_video=download
    with patch('forme_backend.cloud_bridge.validate_claimed',validate):
        bridge.import_job(job,'lease-token')
        bridge.import_job(job,'lease-token')

    imported=store.get_submission(sid)
    assert imported['upload_id']==upload_id
    assert imported['upload']['status']=='needs_capture_review'
    assert imported['upload']['sha256']==sha
    assert len(store.list_submissions())==1
    assert len([c for c in calls if c[1].endswith('/imported')])==2
    bridge.sync_job(sid,None)
    progress=calls[-1][2]
    assert progress['status']=='accepted'
    assert progress['stage']=='queued'
    assert '操作员' in progress['note']
    assert store.transition(upload_id,'needs_capture_review','accepted')
    bridge.sync_job(sid,None)
    assert calls[-1][2]['status']=='accepted'
    assert '审核已通过' in calls[-1][2]['note']

    # A generated candidate must not regress to "queued" / "scale_review"
    # on every subsequent cloud sync just because COLMAP awaits scale review.
    candidate_id='current-trial'
    target=tmp_path/'cover_tasks'/sid/'candidate_print_trial'/candidate_id/'cover_trial_mm.stl'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'test-stl-candidate')
    with patch('forme_backend.cloud_bridge.workflow_snapshot',return_value={'trialCandidate':{'candidateId':candidate_id}}):
        bridge.sync_job(sid,hashlib.sha256(target.read_bytes()).hexdigest())
    assert calls[-1][2]['stage']=='modeling'
    assert 'STL' in calls[-1][2]['note']
