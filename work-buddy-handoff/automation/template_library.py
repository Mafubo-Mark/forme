"""Register supplied cover templates without trusting archive paths or metadata claims."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import struct
import zlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT.parents[2] / 'modols'
LIBRARY = ROOT / 'templates'
NAMES = {
    '01': '祥云', '02': '蜂巢', '03': '流线', '04': '竹影',
    '05': '鳞羽', '06': '通风', '05-magnetic': '鳞羽内嵌磁吸',
}

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def stl_info(path):
    with path.open('rb') as f:
        h = f.read(84)
        if len(h) != 84:
            raise ValueError(f'Invalid STL: {path}')
        count = struct.unpack_from('<I', h, 80)[0]
        low = [float('inf')] * 3
        high = [float('-inf')] * 3
        while block := f.read(50 * 1000):
            for tri in struct.iter_unpack('<12fH', block):
                for axis in range(3):
                    coordinates = (tri[3 + axis], tri[6 + axis], tri[9 + axis])
                    low[axis] = min(low[axis], *coordinates)
                    high[axis] = max(high[axis], *coordinates)
    if path.stat().st_size != 84 + count * 50:
        raise ValueError(f'Invalid binary STL length: {path}')
    return {'triangles': count, 'bytes': path.stat().st_size,
            'bounds_min_max_mm': [[round(x, 3) for x in row] for row in (low, high)]}

def register():
    LIBRARY.mkdir(parents=True, exist_ok=True)
    items = []
    for archive in sorted(INPUT.glob('*.zip')):
        ident = '05-magnetic' if '内嵌磁吸' in archive.name else archive.name[:2]
        if ident not in NAMES:
            raise ValueError(f'Unknown template archive: {archive}')
        dest = LIBRARY / ident
        dest.mkdir(exist_ok=True)
        files = []
        with zipfile.ZipFile(archive) as z:
            entries = [x for x in z.infolist() if not x.is_dir()]
            if len(entries) > 100 or sum(x.file_size for x in entries) > 300_000_000:
                raise ValueError(f'Archive exceeds limits: {archive}')
            for info in entries:
                parts = Path(info.filename).parts
                if len(parts) not in (1, 2) or any(p in ('.', '..') for p in parts):
                    raise ValueError(f'Unsafe archive path: {info.filename}')
                name = parts[-1]
                if name in files:
                    raise ValueError(f'Duplicate filename: {name}')
                files.append(name)
                output = dest / name
                actual_crc = None
                if output.exists():
                    checksum = 0
                    with output.open('rb') as current:
                        for block in iter(lambda: current.read(1024 * 1024), b''):
                            checksum = zlib.crc32(block, checksum)
                    actual_crc = checksum
                if actual_crc != info.CRC:
                    partial = output.with_name(output.name + '.part')
                    with z.open(info) as src, partial.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
                    partial.replace(output)
                if output.stat().st_size != info.file_size:
                    raise ValueError(f'Unexpected extracted size: {output}')
        metadata_name = next((n for n in files if n.endswith('dimensions_and_checks.json') or n == '尺寸与检查.json'), None)
        metadata = json.loads((dest / metadata_name).read_text()) if metadata_name else {}
        meshes = {n: {**stl_info(dest / n), 'sha256': sha(dest / n)} for n in files if n.lower().endswith('.stl')}
        items.append({
            'id': ident, 'name': NAMES[ident], 'source_archive': str(archive),
            'source_sha256': sha(archive), 'directory': str(dest), 'files': sorted(files),
            'meshes': meshes, 'metadata_file': metadata_name,
            'fixing': metadata.get('fixing', '内嵌磁吸；需验证保持力'),
            'nominal_clearance_mm': metadata.get('nominal_clearance_radial_mm', metadata.get('inner_nominal_radial_gap_mm')),
            'shell_height_mm': metadata.get('shell_height_mm', 315.25),
            'has_editable_blend': any(n.lower().endswith('.blend') for n in files),
            'status': 'source_registered_unverified_fit',
        })
    loose = LIBRARY / 'unidentified'
    loose.mkdir(exist_ok=True)
    orphans = []
    for source in sorted(INPUT.glob('*.stl')):
        target = loose / source.name
        if not target.exists():
            shutil.copy2(source, target)
        if sha(target) != sha(source):
            raise ValueError(f'Copy mismatch: {source}')
        orphans.append({'filename': source.name, 'path': str(target), 'sha256': sha(target), **stl_info(target), 'status': 'unidentified_variant_do_not_auto_select'})
    catalog = {'schema_version': 1, 'units_claimed': 'mm', 'coordinate_claim': 'Z up; +Y rear, from source package', 'templates': items, 'unidentified_files': orphans, 'notes': ['Source checks are supplier claims until independently reproduced.', 'No template is approved for physical fit or clinical use.']}
    (LIBRARY / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')
    return catalog

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['register'])
    args = parser.parse_args()
    result = register()
    print(json.dumps({'templates': len(result['templates']), 'unidentified': len(result['unidentified_files']), 'catalog': str(LIBRARY / 'catalog.json')}, ensure_ascii=False))
