"""Package the diagnostic STL as a clearly labelled FreeCAD view file."""
from pathlib import Path

import FreeCAD as App
import Mesh

base = Path('/Volumes/extra/workspace1/projects/test4/gs-experiment/cad-v6-smooth-preview')
doc = App.newDocument('SilhouetteShapeReview')
obj = doc.addObject('Mesh::Feature', 'UnverifiedPreview')
obj.Label = '已否决的诊断模型｜不可用于贴合或生产'
obj.Mesh = Mesh.Mesh(str(base / 'smooth_sleeve_preview.stl'))
obj.addProperty('App::PropertyString', 'Status', 'Review')
obj.Status = 'Rejected: masks derive from defective COLMAP cloud; fit and bolt clearance unverified'
if obj.ViewObject is not None:
    obj.ViewObject.ShapeColor = (0.08, 0.48, 0.5)
doc.recompute()
doc.saveAs(str(base / 'shape_review_only.FCStd'))
App.closeDocument(doc.Name)
print(base / 'shape_review_only.FCStd')
