import bpy
import math
import numpy as np
from mathutils import Vector

PREFIX = "DS Trial"

def get_bbox_bounds(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

ref = bpy.data.objects.get("01 Reference prosthesis | 120 mm top scale")
cover = bpy.data.objects.get("02 COVER | editable Blender modifiers")
if ref is None:
    raise RuntimeError("Reference object not found")

rx0, rx1, ry0, ry1, rz0, rz1 = get_bbox_bounds(ref)
cx = (rx0 + rx1) * 0.5
cy = (ry0 + ry1) * 0.5
H = rz1 - rz0
W = rx1 - rx0
D = ry1 - ry0

# conservative conceptual offsets in mm, not verified fit
offset_side = 3.0
offset_front = 2.5
offset_back = 4.0
z_levels = 14
n_ring = 18

# sample reference silhouette by slicing mesh vertices
ref_verts = [ref.matrix_world @ v.co for v in ref.data.vertices]
zs_all = np.array([p.z for p in ref_verts])
xs_all = np.array([p.x for p in ref_verts])
ys_all = np.array([p.y for p in ref_verts])

def ref_half_profile(z):
    if len(zs_all) == 0:
        return W * 0.5, D * 0.5
    band = max(H * 0.03, 1.0)
    mask = np.abs(zs_all - z) < band
    if mask.sum() < 3:
        return W * 0.5, D * 0.5
    return (xs_all[mask].max() - xs_all[mask].min()) * 0.5, (ys_all[mask].max() - ys_all[mask].min()) * 0.5

# build control rings for a smooth C shape
rings = []
for i in range(z_levels):
    t = i / (z_levels - 1)
    z = rz0 + t * H
    rx, ryd = ref_half_profile(z)
    rx = max(rx, 8.0)
    ryd = max(ryd, 8.0)
    # explicit C-mouth opening angle grows toward back opening
    gap_half = math.radians(14.0 + 6.0 * t)
    ring = []
    for j in range(n_ring):
        a = j / (n_ring - 1)
        # ring runs from front-right to front-left around back opening gap
        theta = (1.0 - a) * (math.pi - gap_half) + a * (math.pi + gap_half)
        # anisotropic outward offset, back side gets larger conservative offset
        nx = math.cos(theta)
        ny = math.sin(theta)
        off = offset_side if abs(nx) > abs(ny) else (offset_front if ny > 0 else offset_back)
        px = cx + (rx + off) * nx
        py = cy + (ryd + off) * ny
        ring.append((px, py, z))
    rings.append(ring)

# adjust top single highest ring into asymmetric double-peak resembling photo
if rings:
    top = rings[-1]
    adjusted = []
    for k, (px, py, pz) in enumerate(top):
        a = k / (len(top) - 1)
        # front peak lower, back peak higher, asymmetric along ring index
        peak = math.sin(math.pi * a)
        front_bias = 1.0 - a
        back_bias = a
        dz = 7.0 * back_bias * peak - 4.0 * front_bias * peak
        adjusted.append((px, py, pz + dz))
    rings[-1] = adjusted

# build mesh
verts = []
faces = []
for ring in rings:
    base = len(verts)
    verts.extend(ring)
for i in range(len(rings) - 1):
    a0 = i * n_ring
    a1 = (i + 1) * n_ring
    for j in range(n_ring - 1):
        faces.append((a0 + j, a0 + j + 1, a1 + j + 1, a1 + j))

mesh = bpy.data.meshes.new(PREFIX + " shell mesh")
mesh.from_pydata(verts, [], faces)
mesh.update()
obj = bpy.data.objects.new(PREFIX + " Shell", mesh)
bpy.context.collection.objects.link(obj)

# modifiers
solid = obj.modifiers.new(name="Solidify", type='SOLIDIFY')
solid.thickness = 2.4
solid.offset = 1.0
bev = obj.modifiers.new(name="Bevel", type='BEVEL')
bev.width = 0.8
bev.segments = 2
subs = obj.modifiers.new(name="Subdivision", type='SUBSURF')
subs.levels = 1
subs.render_levels = 2

# bolt relief: independent open ring, not a bulge on shell
bolt_z = rz0 + H * 0.20
bolt_r = max(5.0, min(W, D) * 0.06)
bverts = []
bverts.append((cx + W * 0.5 + offset_side, cy, bolt_z + bolt_r))
bn = 48
for i in range(bn):
    a = 2.0 * math.pi * i / bn
    bverts.append((cx + W * 0.5 + offset_side, cy + bolt_r * math.sin(a), bolt_z + bolt_r * math.cos(a)))
bverts.append((cx + W * 0.5 + offset_side, cy, bolt_z))
bmesh = bpy.data.meshes.new(PREFIX + " bolt relief mesh")
bfaces = [] for i in range(1, bn): bfaces.append((0, i, i + 1))
bfaces.append((0, bn, 1))
bmesh.from_pydata(bverts, [], bfaces)
bmesh.update()
bobj = bpy.data.objects.new(PREFIX + " Bolt Relief", bmesh)
bpy.context.collection.objects.link(bobj)

print("Created", obj.name, "and", bobj.name)
