import json
from pathlib import Path
import numpy as np
import trimesh

p=Path('/Volumes/extra/workspace1/projects/test4/blender-cover-redesign')
m=trimesh.load_mesh(p/'blender-designed-cover.stl',process=True)
before=len(m.faces)
_,index,count=np.unique(np.sort(m.faces,axis=1),axis=0,return_inverse=True,return_counts=True)
# Exact Boolean can leave an opposing duplicate triangle pair with zero volume.
# Remove both members; preserving only one would leave a non-manifold sheet.
m.update_faces(count[index]==1)
m.remove_unreferenced_vertices()
if not m.is_volume or len(m.split(only_watertight=False))!=1:
 raise RuntimeError('Final cover must be one closed, consistently oriented solid')
m.export(p/'blender-designed-cover.stl')
report={'faces':len(m.faces),'zero_volume_duplicate_faces_removed':before-len(m.faces),
 'watertight':bool(m.is_watertight),'winding_consistent':bool(m.is_winding_consistent),
 'components':1,'volume_mm3':float(m.volume),
 'status':'Blender design review; physical fit and mounting not validated',
 'source_top_scale_mm':120,'shaft_front_measurement_mm':80,
 'wall_modifier_mm':3,'nominal_body_shrinkwrap_offset_mm':8,
 'clearance_note':'Smoothing and designed upper rim change the final local clearance; not a measured 8 mm guarantee.'}
(p/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
