"""Build an editable Blender scene for manual scale inspection.

Run with Blender -b --python this_file. Every generated file stays in workspace1.
The reference cloud is a decimated display copy of the 200 mm calibrated cloud.
The original full cloud remains test4-cloud-calibrated-mm.ply.
"""

import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector, Euler

root = Path('/Volumes/extra/workspace1/projects/test4/hunyuan31-comparison')
report = json.loads((root / 'comparison-report.json').read_text())['best']
sample = np.load(root / 'blender-review-cloud-sample.npz')

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for collection in list(bpy.data.collections):
    if collection.name != bpy.context.scene.collection.name and collection.users == 0:
        bpy.data.collections.remove(collection)

scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 0.001  # 1 Blender coordinate = 1 mm
scene.unit_settings.length_unit = 'MILLIMETERS'

def collection(name):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    return c

cloud_collection = collection('01 CALIBRATED CLOUD | fixed | millimetres')
model_collection = collection('02 HUNYUAN STL | select and scale uniformly')
ruler_collection = collection('03 200 mm DISPLAY RULER')

def material(name, color):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1.0)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.75
    return m

palette = {
    'receiver_cloud': ('Point cloud | receiver | cyan', (0.02, 0.54, 0.70)),
    'tape_cloud': ('Point cloud | yellow band | gold', (0.97, 0.62, 0.03)),
    'shaft_cloud': ('Point cloud | shaft | blue', (0.13, 0.28, 0.82)),
}
offsets = np.array([[0.0, 0.0, 0.8], [0.75, 0.0, -0.35],
                    [-0.375, 0.65, -0.35], [-0.375, -0.65, -0.35]],
                   dtype=np.float32)
face_pattern = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]], dtype=np.int32)
for key, (name, color) in palette.items():
    pts = sample[key]
    vertices = (pts[:, None, :] + offsets[None, :, :]).reshape(-1, 3)
    faces = (face_pattern[None, :, :] +
             (np.arange(len(pts)) * 4)[:, None, None]).reshape(-1, 3)
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices.tolist(), [], faces.tolist())
    data.update()
    obj = bpy.data.objects.new(name, data)
    cloud_collection.objects.link(obj)
    obj.data.materials.append(material(name + ' material', color))
    obj.color = (*color, 1.0)
    obj.hide_select = True

# Import original native-unit STL, then move its mesh vertices so its object
# origin is the visible transition/collar. Uniform scaling keeps this anchor
# in place. Neither the reference cloud nor the 200 mm ruler changes.
bpy.ops.wm.stl_import(filepath=str(root / 'hunyuan31-original.stl'))
stl = bpy.context.object
for c in list(stl.users_collection):
    c.objects.unlink(stl)
model_collection.objects.link(stl)
stl.name = 'HUNYUAN STL | select me | S changes scale around yellow band'
collar = Vector((0.0, 0.05, 0.56))
for vertex in stl.data.vertices:
    vertex.co -= collar
R = Matrix(report['R'])
T = Vector(report['translation_mm'])
old_scale = report['scale_mm_per_stl_unit']
anchor = T + old_scale * (R @ collar)
stl.location = anchor
stl.rotation_mode = 'QUATERNION'
stl.rotation_quaternion = R.to_quaternion()
measurement = report['physical_measurement']
initial_scale = float(measurement['derived_mm_per_stl_unit'])
stl.scale = (initial_scale,) * 3
stl['initial_mm_per_STL_unit'] = initial_scale
stl['measured_top_outer_width_mm'] = 120.0
stl['model_top_outer_xy_span_native_units'] = measurement['stl_native_units']
stl['reference_cloud'] = '200 mm calibrated COLMAP test4; display sample only'
stl['scale_pivot'] = 'yellow transition near original STL (0, 0.05, 0.56)'
stl['review_note'] = 'Change X/Y/Z Scale together, or press S then a factor; model ratio is provisional.'
stl.data.materials.clear()
stl.data.materials.append(material('Hunyuan STL | magenta', (0.83, 0.03, 0.44)))
stl.color = (0.83, 0.03, 0.44, 1.0)
stl.display_type = 'WIRE'
stl.show_in_front = True

# Mark the model points used for the user's 120 mm outer-to-outer measurement.
# Their heights differ because the upper rim is not level; the green line is
# the horizontal XY projection of that span and follows model scale.
green = material('Measured upper outer span | green', (0.03, 0.78, 0.11))
rim_points = [Vector(measurement['rim_point_1_stl_xyz']),
              Vector(measurement['rim_point_2_stl_xyz'])]
for idx, point in enumerate(rim_points, 1):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6,
                                         radius=0.003, location=(0, 0, 0))
    marker = bpy.context.object
    marker.name = f'TOP OUTER EDGE MEASUREMENT POINT {idx}'
    for c in list(marker.users_collection):
        c.objects.unlink(marker)
    model_collection.objects.link(marker)
    marker.parent = stl
    marker.matrix_parent_inverse = Matrix.Identity(4)
    marker.location = point - collar
    marker.data.materials.append(green)
    marker.color = green.diffuse_color
    marker.hide_select = True

line_data = bpy.data.curves.new('120 mm outer XY guide', type='CURVE')
line_data.dimensions = '3D'
line_data.bevel_depth = 0.001
line_data.bevel_resolution = 1
line_spline = line_data.splines.new('POLY')
line_spline.points.add(1)
for i, point in enumerate(rim_points):
    local = Vector((point.x, point.y, 1.095)) - collar
    line_spline.points[i].co = (*local, 1.0)
line_obj = bpy.data.objects.new('TOP OUTER XY WIDTH | 120 mm at measured scale', line_data)
model_collection.objects.link(line_obj)
line_obj.parent = stl
line_obj.matrix_parent_inverse = Matrix.Identity(4)
line_obj.data.materials.append(green)
line_obj.color = green.diffuse_color
line_obj.hide_select = True

def sphere(name, location, radius, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6,
                                         radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    ruler_collection.objects.link(obj)
    obj.data.materials.append(mat)
    obj.color = mat.diffuse_color
    obj.hide_select = True
    return obj

gold = material('Display ruler | orange', (1.0, 0.32, 0.02))
ruler_x = 133.0
ruler_y = 0.0
ruler_z0, ruler_z1 = -300.0, -100.0
bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=1.0, depth=200.0,
                                     location=(ruler_x, ruler_y, (ruler_z0 + ruler_z1)/2))
bar = bpy.context.object
bar.name = 'DISPLAY RULER | 200 mm (not a scan target)'
for c in list(bar.users_collection):
    c.objects.unlink(bar)
ruler_collection.objects.link(bar)
bar.data.materials.append(gold)
bar.color = gold.diffuse_color
bar.hide_select = True
sphere('Ruler start', (ruler_x, ruler_y, ruler_z0), 3.0, gold)
sphere('Ruler end', (ruler_x, ruler_y, ruler_z1), 3.0, gold)

label = bpy.data.curves.new('200 mm text', type='FONT')
label.body = '200 mm reference'
label.size = 9
label.extrude = 0.0
label_obj = bpy.data.objects.new('DISPLAY RULER LABEL', label)
ruler_collection.objects.link(label_obj)
label_obj.location = (ruler_x + 5, ruler_y, ruler_z1 + 8)
label_obj.rotation_euler = (math.pi / 2, 0, math.pi / 2)
label_obj.data.materials.append(gold)
label_obj.hide_select = True

# Open with the adjustable model selected, looking at the whole fitted region.
bpy.ops.object.select_all(action='DESELECT')
stl.select_set(True)
bpy.context.view_layer.objects.active = stl
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        space = area.spaces.active
        space.shading.type = 'SOLID'
        space.shading.color_type = 'OBJECT'
        space.shading.light = 'STUDIO'
        space.shading.show_cavity = False
        space.region_3d.view_perspective = 'ORTHO'
        space.region_3d.view_distance = 650
        space.region_3d.view_location = (0, 0, -155)
        space.region_3d.view_rotation = Euler((math.radians(75), 0,
                                                math.radians(25)), 'XYZ').to_quaternion()

scene['Instructions'] = 'Select magenta STL; S 1.05 = +5%, S 0.95 = -5%. Cloud and 200 mm ruler stay fixed.'
scene['Scale explanation'] = 'STL has no native mm unit. Scene coordinates are mm from the 200 mm COLMAP bar.'
scene['Initial model scale'] = f'{initial_scale:.3f} mm per STL unit from user-measured 120 mm top outer XY width.'
scene['Original high-resolution cloud'] = str(root / 'test4-cloud-calibrated-mm.ply')
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'hunyuan31-scale-review.blend'))
print('saved', root / 'hunyuan31-scale-review.blend', flush=True)
print('STL pivot (mm):', tuple(round(x, 3) for x in anchor), flush=True)
print('STL initial uniform scale:', initial_scale, flush=True)
