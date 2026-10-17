"""Small local MCP stdio bridge for WorkBuddy (legacy initialize lifecycle)."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
BACKEND_SRC = Path(__file__).resolve().parents[2] / 'forme-backend' / 'src'
sys.path.insert(0, str(BACKEND_SRC))
from forme_backend.cover_automation import prepare_task, task_status
from forme_backend.concept_cover import CoverGateError, build_candidate
from forme_backend.store import Store
from forme_backend import scan_workflow as scan
from fit_template import CATALOG, FitError, validate
from reference_preflight import DEFAULT_REFERENCE, check

TOOLS = [
 {'name':'get_scan_workflow','description':'Read scan-first production status, current task paths and reviewed recipe. Default no Hunyuan. Prepare actual task-specific evidence before approval.', 'inputSchema':{'type':'object','properties':{'submission_id':{'type':'string'}},'required':['submission_id'],'additionalProperties':False}},
 {'name':'approve_scan_geometry','description':'Bind explicit current-task ruler-length and geometry confirmation to exact reviewed file hashes. Requires existing user authorization; cannot invent physical length or approve unknown directions.', 'inputSchema':{'type':'object','properties':{'submission_id':{'type':'string'},'confirmation':{'type':'object'}},'required':['submission_id','confirmation'],'additionalProperties':False}},
 {'name':'queue_scan_cover','description':'Queue approved scan-first fit, rim trim, bolt opening, mesh checks and STL delivery. Durable and idempotent; never asserts physical fit.', 'inputSchema':{'type':'object','properties':{'submission_id':{'type':'string'}},'required':['submission_id'],'additionalProperties':False}},

 {'name':'list_frontend_tasks','description':'List recent Forme frontend submissions and cover automation readiness. No patient media is returned.',
  'inputSchema':{'type':'object','properties':{},'additionalProperties':False}},
 {'name':'get_frontend_cover_task','description':'Get a submission cover task readiness and local handoff manifest path.',
  'inputSchema':{'type':'object','properties':{'submission_id':{'type':'string'}},'required':['submission_id'],'additionalProperties':False}},
 {'name':'prepare_frontend_cover_task','description':'Create a local WorkBuddy intake manifest from a frontend submission and template. This does not generate a cover or approve registration.',
  'inputSchema':{'type':'object','properties':{'submission_id':{'type':'string'},'template_id':{'type':'string'}},'required':['submission_id','template_id'],'additionalProperties':False}},
 {'name':'list_cover_templates','description':'List registered cover styles and source integrity metadata; fit status remains unverified.',
  'inputSchema':{'type':'object','properties':{},'additionalProperties':False}},
 {'name':'preflight_reference','description':'Compare a template with the current segmented reference and report coordinate/height blockers.',
  'inputSchema':{'type':'object','properties':{'template_id':{'type':'string'}},'required':['template_id'],'additionalProperties':False}},
 {'name':'validate_fit_proposal','description':'Check a structured fit proposal against source hash, registration, units, axes and 3 mm morph bounds.',
  'inputSchema':{'type':'object','properties':{'proposal':{'type':'object'}},'required':['proposal'],'additionalProperties':False}},
 {'name':'build_concept_cover','description':'Build a bounded digital concept only after this submission has an operator-approved ruler, reviewed subject crop and template registration. Never asserts physical fit.',
  'inputSchema':{'type':'object','properties':{'submission_id':{'type':'string'},'candidate_id':{'type':'string','pattern':'^[a-z0-9_-]{1,40}$'},'proposal':{'type':'object'}},'required':['submission_id','candidate_id','proposal'],'additionalProperties':False}},
]

def tool_call(name,args):
    if name in ('get_scan_workflow','approve_scan_geometry','queue_scan_cover'):
        data_dir=Path(os.environ.get('FORME_DATA_DIR',str(BACKEND_SRC.parent/'data'))).resolve()
        store=Store(data_dir);sid=args['submission_id']
        if not store.get_submission(sid):raise ValueError('SUBMISSION_NOT_FOUND')
        if name=='get_scan_workflow':return {**scan.snapshot(data_dir,sid),'taskRoot':str(scan.root(data_dir,sid)),'skillPath':str(BACKEND_SRC.parent.parent/'work-buddy-handoff/skills/forme-scan-workflow/SKILL.md')}
        if name=='approve_scan_geometry':return scan.approve(data_dir,sid,store,args['confirmation'])
        return scan.enqueue(data_dir,sid,store)

    if name in ('list_frontend_tasks','get_frontend_cover_task','prepare_frontend_cover_task'):
        data_dir = Path(os.environ.get('FORME_DATA_DIR',str(BACKEND_SRC.parent / 'data'))).resolve()
        store = Store(data_dir)
        if name == 'list_frontend_tasks':
            return {'tasks':[{'submission_id':s['id'],'filename':s['filename'],
                              'created_at':s['created_at'],'capture_status':s['status'],
                              'cover':task_status(store,data_dir,s['id']), 'scanWorkflow':scan.snapshot(data_dir,s['id'])}
                             for s in store.list_submissions(limit=20)]}
        submission_id=args['submission_id']
        if name == 'get_frontend_cover_task':
            return task_status(store,data_dir,submission_id)
        return prepare_task(store,data_dir,submission_id,args['template_id'])
    if name=='list_cover_templates':
        c=json.loads(CATALOG.read_text())
        return {'templates':[{'id':x['id'],'name':x['name'],'fixing':x['fixing'],
                'source_sha256':x['source_sha256'],'has_editable_blend':x['has_editable_blend'],
                'status':x['status']} for x in c['templates']],
                'unidentified_files':len(c['unidentified_files'])}
    if name=='preflight_reference':
        return check(args['template_id'],DEFAULT_REFERENCE)
    if name in ('validate_fit_proposal','build_concept_cover'):
        if name == 'build_concept_cover':
            data_dir = Path(os.environ.get('FORME_DATA_DIR', str(BACKEND_SRC.parent / 'data'))).resolve()
            geometry_python = os.environ.get('FORME_GEOMETRY_PYTHON',
                str(BACKEND_SRC.parents[3] / 'apps/drawing-with-gaussians/.venv/bin/python'))
            submission_id = args['submission_id']
            store = Store(data_dir)
            submission = store.get_submission(submission_id)
            model = store.model_job_for_submission(submission_id)
            if not submission or not model or model['stage'] != 'scale_review':
                raise CoverGateError('COLMAP_RECONSTRUCTION_REQUIRED')
            views = store.get_view_review(submission_id)
            if submission['upload']['status'] != 'accepted' or not views or views['status'] != 'reviewed':
                raise CoverGateError('CAPTURE_AND_VIEWS_REVIEW_REQUIRED')
            if not Path(geometry_python).is_file():
                raise CoverGateError('GEOMETRY_PYTHON_NOT_CONFIGURED')
            cloud = data_dir / 'model_jobs' / model['id'] / 'dense' / 'fused.ply'
            if not cloud.is_file():
                raise CoverGateError('COLMAP_CLOUD_REQUIRED')
            return build_candidate(data_dir / 'cover_tasks' / submission_id,
                                   submission['upload']['sha256'], cloud, args['candidate_id'],
                                   args['proposal'], geometry_python,
                                   Path(__file__).resolve().parent / 'fit_template.py')
        spec=args['proposal']
        c=json.loads(CATALOG.read_text())
        template=next((x for x in c['templates'] if x['id']==spec.get('template_id')),None)
        if template is None:raise FitError('TEMPLATE_NOT_FOUND')
        validate(spec,template)
        if name=='validate_fit_proposal':return {'status':'VALID_FOR_CONCEPT_MORPH','fit_verified':False}
    raise ValueError('UNKNOWN_TOOL')

def reply(request):
    method=request.get('method')
    if method=='initialize':
        proposed=request.get('params',{}).get('protocolVersion','2025-06-18')
        version=proposed if proposed in ('2024-11-05','2025-03-26','2025-06-18','2025-11-25') else '2025-06-18'
        return {'protocolVersion':version,'capabilities':{'tools':{'listChanged':False}},
                'serverInfo':{'name':'forme-cover-fit','version':'0.2.0'},
                'instructions':'Use get_scan_workflow for the scan-first pipeline. Follow forme-scan-workflow skill; default no Hunyuan. Current input hashes and geometry confirmation are required. Historical fit feedback applies only to its recorded mesh hashes. Legacy bounded concepts use their existing registration gate.'}
    if method=='ping':return {}
    if method=='tools/list':return {'tools':TOOLS}
    if method=='tools/call':
        params=request.get('params') or {}
        try:
            value=tool_call(params.get('name'),params.get('arguments') or {})
            return {'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
        except (KeyError,ValueError,TypeError,OSError) as exc:
            return {'isError':True,'content':[{'type':'text','text':str(exc)}]}
    raise ValueError('METHOD_NOT_FOUND')

def serve():
    for line in sys.stdin.buffer:
        if len(line)>1_000_000:break
        try:
            request=json.loads(line)
            if not isinstance(request,dict):raise ValueError('INVALID_REQUEST')
            if 'id' not in request:continue
            try:result={'result':reply(request)}
            except ValueError as exc:result={'error':{'code':-32601,'message':str(exc)}}
            response={'jsonrpc':'2.0','id':request['id'],**result}
        except Exception as exc:
            response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':str(exc)}}
        sys.stdout.write(json.dumps(response,ensure_ascii=False,separators=(',',':'))+'\n')
        sys.stdout.flush()

if __name__=='__main__':serve()
