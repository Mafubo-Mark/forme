"""Conservative axis/extent preflight before any cover fitting."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from template_library import ROOT, stl_info

DEFAULT_REFERENCE = ROOT.parent / 'colmap-retune-20261002/smooth-mesh/upper-body-segmented-reference-mm.stl'

def check(template_id, reference):
    catalog = json.loads((ROOT/'templates/catalog.json').read_text())
    template = next((x for x in catalog['templates'] if x['id']==template_id), None)
    if template is None: raise ValueError('TEMPLATE_NOT_FOUND')
    info = stl_info(reference)
    ref_min, ref_max = info['bounds_min_max_mm']
    ref_span = [round(b-a,3) for a,b in zip(ref_min, ref_max)]
    mesh_names = ('前壳.stl','后壳.stl') if template_id == '05-magnetic' else ('front.stl','rear.stl')
    shapes = [template['meshes'][name]['bounds_min_max_mm'] for name in mesh_names]
    shell_min = [min(x[0][i] for x in shapes) for i in range(3)]
    shell_max = [max(x[1][i] for x in shapes) for i in range(3)]
    shell_span = [round(b-a,3) for a,b in zip(shell_min,shell_max)]
    ratio = ref_span[2]/shell_span[2]
    raw_gap = [round(ref_min[i]-shell_min[i],3) for i in range(3)]
    return {'status':'NEEDS_COORDINATE_REGISTRATION','template_id':template_id,
            'reference':str(reference),'reference_triangles':info['triangles'],
            'reference_bounds_min_max_mm':[ref_min,ref_max],
            'reference_span_mm':ref_span,'template_bounds_min_max_mm':[shell_min,shell_max],
            'template_span_mm':shell_span,'reference_to_template_height_ratio':round(ratio,4),
            'raw_minima_delta_mm':raw_gap,
            'automatic_fit_permitted':False,
            'reasons':['Reference is an incomplete exploratory segmented surface, not a verified full socket.',
                       'Raw STL frames differ; rigid registration against physical markers is required.',
                       'Fastener geometry and confidence masks are not measured.']}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--template',default='04')
    parser.add_argument('--reference',type=Path,default=DEFAULT_REFERENCE)
    parser.add_argument('--output',type=Path,default=ROOT/'output/template_adaptation/reference_preflight.json')
    args=parser.parse_args()
    report=check(args.template,args.reference)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
