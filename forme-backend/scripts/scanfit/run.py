"""Execute the validated scan recipe without importing one-off patient scripts."""
from pathlib import Path
import argparse,ast,hashlib,json,shutil,subprocess,sys,zipfile
import numpy as np,trimesh
P=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def call(args,log):
 with log.open('w') as f:r=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT,check=False,timeout=1800)
 if r.returncode:raise RuntimeError('STAGE_FAILED:'+log.name)
def clean(p):
 m=trimesh.load_mesh(p,process=True);cs=sorted(m.split(only_watertight=False),key=lambda c:len(c.faces),reverse=True)
 if not cs or any(abs(c.volume)>1e-6 or len(c.faces)>4 for c in cs[1:]):raise ValueError('NONTRIVIAL_DISCONNECTED_GEOMETRY:'+p.name)
 m=cs[0]
 if not(m.is_watertight and m.is_winding_consistent and m.volume>0):raise ValueError('MESH_TOPOLOGY_FAILED:'+p.name)
 m.export(p);return m

def run(out,blender):
 cfg=json.loads((out/'run_config.json').read_text());(out/'logs').mkdir();(out/'symmetric_base').mkdir()
 base=P.parents[2]/'work-buddy-handoff/production-bases'/cfg['templateId']
 for side in ['front','rear']:
  source=base/f'{side}.stl'
  if sha(source)!=cfg['baseHashes'][side]:raise ValueError('TEMPLATE_HASH_MISMATCH')
  shutil.copy2(source,out/'symmetric_base'/source.name)
 for stage in ['fit_profile','rim_limit']:call([sys.executable,str(P/f'{stage}.py'),str(out)],out/'logs'/f'{stage}.log')
 call([blender,'--background','--threads','4','--python',str(P/'finish_mesh.py'),'--',str(out)],out/'logs/booleans.log')
 parts={side:clean(out/f'cover_{side}_mm.stl') for side in ['front','rear']}
 call([blender,'--background','--threads','4','--python',str(P/'render_review.py'),'--',str(out)],out/'logs/render_review.log')
 call([blender,'--background','--threads','4','--python',str(P/'bolt_check.py'),'--',str(out)],out/'logs/bolt_check.log')
 overlap=json.loads((out/'seam_bvh_review.json').read_text())
 if overlap['triangleOverlapPairCount']!=0:raise ValueError('ASSEMBLY_INTERSECTION')
 # Inspect finalized booleans, not only the intended target field.
 Z=np.arange(float(cfg['bottomZMm']),321.,10.);A=-np.pi+(np.arange(36)+.5)*2*np.pi/36;CENTER=np.array(cfg['centerXYMm']);env={'np':np,'trimesh':trimesh,'Z':Z,'A':A,'CENTER':CENTER,'BOTTOM':float(cfg['bottomZMm'])}
 fn=next(n for n in ast.parse((P/'fit_profile.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='source_profile');exec(compile(ast.Module(body=[fn],type_ignores=[]),'profile','exec'),env);actual=env['source_profile'](list(parts.values()));fields=np.load(out/'radial_profiles.npz');valid=fields['observedMask']&np.isfinite(actual);valid[abs(Z-cfg['bolt']['baseMm'][2])<=cfg['bolt']['diameterMm']/2+10,:]=False;gap=(actual-fields['observedRaw'])[valid]
 if not len(gap) or np.min(gap)<.5:raise ValueError('INSUFFICIENT_OBSERVED_CLOUD_CLEARANCE')
 coverage=float(fields['observedMask'].mean())
 if coverage<.7:raise ValueError('INSUFFICIENT_PROFILE_COVERAGE')
 lower=fields['observedMask'][Z<150]
 if np.any(lower.sum(axis=1)<18):raise ValueError('LOWER_BODY_INCOMPLETE')
 for side,m in parts.items():m.export(out/f'cover_{side}.stl')
 combined=trimesh.util.concatenate(list(parts.values()));combined.export(out/'cover_trial_mm.stl')
 for p in (out/'fit_coupons').glob('*.stl'):clean(p)
 report={'status':'STL_CANDIDATE_READY','method':cfg['method'],'candidateId':out.name,'sourceVideoSha256':cfg['sourceVideoSha256'],'referenceReviewSha256':cfg['referenceReviewSha256'],'units':'mm','requiredBuildHeightMm':float(combined.extents[2]),'profileCoverage':coverage,'radialGapQuantilesMm':np.quantile(gap,[0,.01,.5,.95,1]).tolist(),'gapScope':'actual finalized section first-hit vs measured outer q98, omit bolt-height band and absent shell directions; not independent metrology','physicalFitVerified':False,'slicerVerified':False,'manufacturingApproved':False,'remainingReview':['target printer/material and sampled thin features','current candidate physical fit and fasteners'],'parts':{s:{'file':f'cover_{s}.stl','sha256':sha(out/f'cover_{s}.stl'),'boundsMm':m.bounds.tolist(),'watertight':True,'singleComponent':True} for s,m in parts.items()}}
 (out/'README_ZH.md').write_text('本包为毫米 STL 数字试样。先试配局部件，再决定是否整件打印。原视频标尺、轴线、上缘与螺栓已由本单批准记录绑定；这不等于此新单已经实物试戴。前后片在同一装配坐标。短段试配件 Z 已移到从零开始。切片按100%导入，不自动缩放。\n')
 names=['cover_front.stl','cover_rear.stl','cover_trial_mm.stl','preview_front.png','preview_side.png','seam_bvh_review.json','bolt_clearance_review.json','wall_thickness_review.json','run_config.json','README_ZH.md']+[str(p.relative_to(out)) for p in (out/'fit_coupons').glob('*.stl')]
 report['files']={name:sha(out/name) for name in names};(out/'release_review.json').write_text(json.dumps(report,indent=2))
 with zipfile.ZipFile(out/'stl_delivery.zip','w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
  for name in names+['release_review.json']:z.write(out/name,name)
 with zipfile.ZipFile(out/'stl_delivery.zip') as z:
  if z.testzip():raise ValueError('ZIP_INTEGRITY_FAILED')
 # Delivery archive hash is separate to avoid a report/archive circular digest.
 (out/'delivery_sha256.json').write_text(json.dumps({'stl_delivery.zip':sha(out/'stl_delivery.zip')}))
 print(json.dumps(report),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--blender',required=True);args=p.parse_args();run(args.output.resolve(),args.blender)
