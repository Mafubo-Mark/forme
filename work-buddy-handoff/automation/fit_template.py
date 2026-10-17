"""Bounded, reproducible low-frequency cover morph from an approved registration.

This moves the STL shell as a concept candidate. Fasteners, inner clearance and
physical retention must be rebuilt/verified before printing for use.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'templates/catalog.json'
TRI = struct.Struct('<12fH')

def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

class FitError(ValueError):
    pass

def validate(spec, template):
    if spec.get('schema_version') != 1 or spec.get('template_id') != template['id']:
        raise FitError('SPEC_TEMPLATE_MISMATCH')
    if spec.get('source_sha256') != template['source_sha256']:
        raise FitError('SOURCE_HASH_MISMATCH')
    registration = spec.get('registration', {})
    if registration.get('verified') is not True:
        raise FitError('REGISTRATION_NOT_VERIFIED')
    if registration.get('units') != 'mm' or registration.get('z_up') is not True or registration.get('rear_positive_y') is not True:
        raise FitError('AXES_OR_UNITS_NOT_CONFIRMED')
    if registration.get('reference_artifact') is None or registration.get('evidence') is None:
        raise FitError('REGISTRATION_EVIDENCE_MISSING')
    controls = spec.get('controls', [])
    if len(controls) < 2 or len(controls) > 30:
        raise FitError('INVALID_CONTROLS')
    last = -math.inf
    for c in controls:
        if set(c) != {'z_mm', 'dx_mm', 'dy_mm', 'radial_x_mm', 'radial_y_mm'}:
            raise FitError('INVALID_CONTROL_FIELDS')
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in c.values()):
            raise FitError('NONFINITE_CONTROL')
        if c['z_mm'] <= last or any(abs(c[k]) > 3 for k in ('dx_mm','dy_mm','radial_x_mm','radial_y_mm')):
            raise FitError('CONTROL_OUT_OF_BOUNDS')
        worst_x = abs(c['dx_mm']) + abs(c['radial_x_mm'])
        worst_y = abs(c['dy_mm']) + abs(c['radial_y_mm'])
        if math.hypot(worst_x, worst_y) > 3:
            raise FitError('TOTAL_MOVE_EXCEEDS_3_MM')
        last = c['z_mm']
    if controls[0]['z_mm'] > 0 or controls[-1]['z_mm'] < template['shell_height_mm']:
        raise FitError('CONTROLS_DO_NOT_COVER_SHELL')
    if spec.get('approval') != 'concept_geometry_only':
        raise FitError('CONCEPT_SCOPE_REQUIRED')
    center = spec.get('template_axis_xy_mm')
    if not isinstance(center,list) or len(center)!=2 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in center):
        raise FitError('TEMPLATE_AXIS_REQUIRED')
    if not all(abs(x)<100 for x in center):
        raise FitError('TEMPLATE_AXIS_OUT_OF_BOUNDS')
    return controls

def interpolate(controls, z):
    if z <= controls[0]['z_mm']:
        return controls[0]
    if z >= controls[-1]['z_mm']:
        return controls[-1]
    for a,b in zip(controls,controls[1:]):
        if a['z_mm'] <= z <= b['z_mm']:
            t = (z-a['z_mm'])/(b['z_mm']-a['z_mm'])
            t = t*t*(3-2*t)
            return {k: a[k]*(1-t)+b[k]*t for k in ('dx_mm','dy_mm','radial_x_mm','radial_y_mm')}
    raise AssertionError

def warp_vertex(v, controls, center):
    x,y,z = v
    c = interpolate(controls,z)
    angle = math.atan2(y-center[1],x-center[0])
    return (x+c['dx_mm']+c['radial_x_mm']*math.cos(angle),
            y+c['dy_mm']+c['radial_y_mm']*math.sin(angle), z)

def warp_stl(source, target, controls, center):
    max_move = 0.0
    bbox = [[math.inf]*3,[-math.inf]*3]
    with source.open('rb') as src, target.open('wb') as dst:
        header=src.read(84)
        count=struct.unpack_from('<I',header,80)[0]
        if source.stat().st_size != 84+50*count:
            raise FitError('INVALID_STL')
        dst.write(header)
        for _ in range(count):
            record=TRI.unpack(src.read(50))
            old=[record[i:i+3] for i in (3,6,9)]
            new=[warp_vertex(v,controls,center) for v in old]
            for a,b in zip(old,new):
                max_move=max(max_move,math.dist(a,b))
                for j in range(3):
                    bbox[0][j]=min(bbox[0][j],b[j]);bbox[1][j]=max(bbox[1][j],b[j])
            u=[new[1][i]-new[0][i] for i in range(3)]
            v=[new[2][i]-new[0][i] for i in range(3)]
            normal=(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
            norm=math.sqrt(sum(x*x for x in normal))
            if norm>0:normal=tuple(x/norm for x in normal)
            dst.write(TRI.pack(*normal,*new[0],*new[1],*new[2],record[-1]))
    return {'triangles':count,'max_vertex_move_mm':round(max_move,4),'bbox_min_max_mm':[[round(x,3) for x in row] for row in bbox]}

def run(spec_path, output_dir):
    spec=json.loads(Path(spec_path).read_text())
    catalog=json.loads(CATALOG.read_text())
    template=next((x for x in catalog['templates'] if x['id']==spec.get('template_id')),None)
    if template is None:raise FitError('TEMPLATE_NOT_FOUND')
    controls=validate(spec,template)
    center=spec['template_axis_xy_mm']
    folder=Path(template['directory'])
    pair=['前壳.stl','后壳.stl'] if template['id']=='05-magnetic' else ['front.stl','rear.stl']
    for name in pair:
        if not (folder/name).is_file():raise FitError('MISSING_SHELL_PART')
        if file_sha256(folder/name) != template['meshes'][name]['sha256']:
            raise FitError('SHELL_SOURCE_HASH_MISMATCH')
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    checks={}
    for name in pair:
        checks[name]=warp_stl(folder/name,output/name,controls,center)
        checks[name]['sha256'] = file_sha256(output/name)
    report={'status':'CONCEPT_CANDIDATE_REVIEW_REQUIRED','template_id':template['id'],
            'source_sha256':template['source_sha256'],'registration':spec['registration'],
            'controls':controls,'mesh_metrics':checks,
            'outstanding':['measure true inner clearance and wall thickness','verify front/rear seam and opening continuity','rebuild or verify fixing dimensions and retention','check self intersection and reference penetration','print fit coupons and test on physical prosthesis']}
    (output/'fit_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (output/'fit_spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('spec');parser.add_argument('output')
    args=parser.parse_args()
    try:print(json.dumps(run(args.spec,args.output),ensure_ascii=False))
    except FitError as exc:parser.error(str(exc))
