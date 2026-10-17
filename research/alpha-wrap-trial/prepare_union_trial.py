"""Add Hunyuan body samples to CGAL's point-set input; hold out 20% for audit."""
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
scan_train=np.load(HERE/'input_points.npz')['train']
ref=np.load(HERE/'eval_reference.npz')
model=ref['model'];old_gap=ref['model_gap_old']
rng=np.random.default_rng(20260930)
holdout=rng.random(len(model))<.2
model_train=model[~holdout]
model_test=model[holdout]
points=np.vstack((scan_train,model_train))
np.savetxt(HERE/'union_train_points.xyz',points,fmt='%.6f')
scan_test=ref['scan']
np.savetxt(HERE/'union_eval_queries.xyz',np.vstack((scan_test,model_test)),fmt='%.6f')
np.savez_compressed(HERE/'union_eval_reference.npz',scan_count=len(scan_test),
                    scan_gap_old=ref['scan_gap_old'],model_gap_old=old_gap[holdout],
                    scan=scan_test,model=model_test,model_holdout_mask=holdout)
report={'scan_train_points':len(scan_train),'hunyuan_train_points':len(model_train),
        'scan_holdout_points':len(scan_test),'hunyuan_holdout_points':len(model_test),
        'model_source':'Hunyuan v2, aligned-mm STL, surface sampled and axis converted; covered C sector only',
        'seed':20260930}
(HERE/'union_input_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(report)
