"""Reproducible same-query comparison for old shell and CGAL trials."""
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
ref=np.load(HERE/'union_eval_reference.npz')
n=int(ref['scan_count'])
mask=ref['model_holdout_mask']

def stats(values):
    x=np.asarray(values)
    return {'count':len(x),'negative_count':int(np.count_nonzero(x<0)),
            'below_2mm_count':int(np.count_nonzero(x<2)),
            'min_mm':round(float(x.min()),2),'p01_mm':round(float(np.quantile(x,.01)),2),
            'median_mm':round(float(np.median(x)),2)}

results={}
results['existing_photo_hull_C_shell']={
    'scan':stats(ref['scan_gap_old']),'hunyuan':stats(ref['model_gap_old']),
    'metric':'radial inner-wall gap'}
for name in ['scan_only_a4_o5','union_a4_o5','union_a4_o7','union_a4_o8','union_a8_o7','union_a16_o7','union_a16_o8']:
    file=(HERE/'eval_a4_o5.csv' if name.startswith('scan_only')
          else HERE/f'union_eval_{name.removeprefix("union_")}.csv')
    x=np.genfromtxt(file,delimiter=',',skip_header=1)[:,-1]
    model=x[n:] if name.startswith('union') else x[n:][mask]
    results[name]={'scan':stats(x[:n]),'hunyuan':stats(model),
                   'metric':'signed nearest mesh-boundary distance; positive inside wrap'}
report={'status':'CGAL ALPHA WRAPPING EXPERIMENT; NO FIT-READY SHELL',
        'common_query':'26,338 held-out scan points plus 7,389 held-out Hunyuan surface points; corrected axis z30-265mm in C-shell active cells',
        'source':'scan-only and scan+Hunyuan point-set alpha wrapping, CGAL 6.2.1 C++',
        'results':results,
        'caveats':['CGAL wraps are closed object envelopes with internal cavities, not exterior C shells',
                   'Alpha wrapping reintroduces the yellow-band bulges and lower roughness',
                   'Upper rim above z275 remains unavailable in this input',
                   'Model alignment and physical dimensions are approximate',
                   'Point tests do not prove continuous insertion or real-world fit']}
(HERE/'trial_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
for name,v in results.items():
    print(name, 'scan',v['scan'],'Hunyuan',v['hunyuan'])
