"""Single-consumer durable cover queue. No paid or external AI calls."""
import argparse,fcntl,os,time
from pathlib import Path
from .config import Settings
from .store import Store
from .scan_workflow import execute,read,write

def main():
 p=argparse.ArgumentParser();p.add_argument('--once',action='store_true');args=p.parse_args();settings=Settings.from_env();data=settings.data_dir;data.mkdir(parents=True,exist_ok=True);store=Store(data)
 with (data/'scan_worker.lock').open('a+') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  # Never silently restart or overwrite partially completed meshes after a crash.
  for file in (data/'cover_tasks').glob('*/scan_workflow.json'):
   state=read(file)
   if state.get('status')=='running':state.update(status='failed',stage='stopped',error='WORKER_INTERRUPTED_REVIEW_AND_REQUEUE');write(file,state)
  while True:
   worked=False
   for file in (data/'cover_tasks').glob('*/scan_workflow.json'):
    if read(file).get('status')=='queued':
     execute(data,file.parent.name,store,settings.geometry_python,os.environ.get('FORME_BLENDER','/Volumes/extra/workspace1/apps/Blender.app/Contents/MacOS/Blender'));worked=True;break
   if args.once:break
   if not worked:time.sleep(3)
if __name__=='__main__':main()
