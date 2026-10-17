"""Local agent entrypoint; no credential printing and no public-network calls."""
from pathlib import Path
import argparse,json,sys,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from forme_backend import scan_workflow as s
from forme_backend.store import Store

def main():
 p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--submission',required=True);p.add_argument('action',choices=['status','start','approve','queue']);p.add_argument('--confirmation',type=Path);p.add_argument('--confirm-capture-and-target',action='store_true');args=p.parse_args();data=args.data_dir.resolve();store=Store(data);sub=store.get_submission(args.submission)
 if not sub:raise s.ScanError('SUBMISSION_NOT_FOUND')
 if args.action=='start':
  if not args.confirm_capture_and_target:raise s.ScanError('CAPTURE_AND_PHYSICAL_TARGET_CONFIRMATION_REQUIRED')
  if sub['upload']['status']=='needs_capture_review':
   if not store.transition(sub['upload_id'],'needs_capture_review','accepted',reason_code='CAPTURE_REVIEW_APPROVED',review_notes='Agent按用户授权核对视频和实体标尺后启动点云'):raise s.ScanError('CAPTURE_STATE_CHANGED')
  elif sub['upload']['status']!='accepted':raise s.ScanError('CAPTURE_QUALITY_REVIEW_REQUIRED')
  with s.lock(s.root(data,args.submission)):
   if not store.model_job_for_submission(args.submission):store.create_model_job(str(uuid.uuid4()),args.submission)
   if not (s.root(data,args.submission)/'scan_workflow.json').is_file():s.write(s.root(data,args.submission)/'scan_workflow.json',{'status':'awaiting_reference','stage':'reconstruction','method':s.METHOD})
 if args.action=='approve':
  if not args.confirmation:raise s.ScanError('CONFIRMATION_FILE_REQUIRED')
  s.approve(data,args.submission,store,s.read(args.confirmation))
 if args.action=='queue':s.enqueue(data,args.submission,store)
 print(json.dumps(s.snapshot(data,args.submission),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
