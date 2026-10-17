"""Report geometry checks for the Pixal3D export (native model units)."""

from pathlib import Path
import numpy as np
import trimesh
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

root = Path('/Volumes/extra/workspace1/projects/test4/pixal3d-trial')
for name in ('test4_pixal3d_textured.glb',):
    mesh = trimesh.load(root / name, force='mesh', process=False)
    print(name, 'loaded', flush=True)
    if name.endswith('.glb'):
        mesh.merge_vertices(merge_tex=True, merge_norm=True, digits_vertex=5)
        print('UV seam vertices welded', flush=True)
    counts = np.bincount(mesh.edges_unique_inverse,
                         minlength=len(mesh.edges_unique))
    print('edge incidences computed', flush=True)
    print('vertices:', len(mesh.vertices), 'triangles:', len(mesh.faces))
    print('extents:', [round(float(x), 6) for x in mesh.extents])
    print('boundary edges:', int(np.count_nonzero(counts == 1)))
    print('nonmanifold edges (>2 faces):', int(np.count_nonzero(counts > 2)))
    print('watertight:', mesh.is_watertight)
    edges = mesh.edges_unique
    adj = csr_matrix((np.ones(len(edges), dtype=np.int8),
                      (edges[:, 0], edges[:, 1])),
                     shape=(len(mesh.vertices), len(mesh.vertices)))
    ncomp, labels = connected_components(adj, directed=False)
    face_counts = np.bincount(labels[mesh.faces[:, 0]], minlength=ncomp)
    print('connected components:', ncomp)
    print('largest-component face fraction:',
          round(float(face_counts.max() / len(mesh.faces)), 6))
