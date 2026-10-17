"""Headless neutral-material turntable preview for the first Pixal3D mesh."""

from pathlib import Path
import math
import sys

import bpy
from mathutils import Vector


ROOT = Path('/Volumes/extra/workspace1/projects/test4/pixal3d-trial')
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
GLB = Path(argv[0]) if argv else ROOT / 'test4_pixal3d_shape.glb'
ROOT = GLB.parent
TEXTURED = 'textured' in GLB.stem
OUT = ROOT / ('mesh-preview-textured' if TEXTURED else 'mesh-preview')
OUT.mkdir(exist_ok=True)

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
if GLB.suffix.lower() == '.stl':
    bpy.ops.wm.stl_import(filepath=str(GLB))
else:
    bpy.ops.import_scene.gltf(filepath=str(GLB))
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError('GLB had no mesh')

if not TEXTURED:
    mat = bpy.data.materials.new('Neutral Gray')
    mat.diffuse_color = (0.62, 0.68, 0.73, 1.0)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (0.62, 0.68, 0.73, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.72
    for obj in meshes:
        obj.data.materials.clear()
        obj.data.materials.append(mat)

bpy.context.view_layer.update()
coords = [obj.matrix_world @ Vector(corner)
          for obj in meshes for corner in obj.bound_box]
mins = Vector(tuple(min(p[i] for p in coords) for i in range(3)))
maxs = Vector(tuple(max(p[i] for p in coords) for i in range(3)))
center = (mins + maxs) / 2
extents = maxs - mins
long_axis = max(range(3), key=lambda i: extents[i])
up = Vector(tuple(1 if i == long_axis else 0 for i in range(3)))
side_axes = [i for i in range(3) if i != long_axis]
a = Vector(tuple(1 if i == side_axes[0] else 0 for i in range(3)))
b = Vector(tuple(1 if i == side_axes[1] else 0 for i in range(3)))

world = bpy.context.scene.world or bpy.data.worlds.new('World')
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.8, 0.83, 0.86, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.8

def area_light(name, direction, energy, size):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = energy
    data.shape = 'DISK'
    data.size = size
    lamp = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(lamp)
    lamp.location = center + direction * 3
    lamp.rotation_euler = (center - lamp.location).to_track_quat('-Z', 'Y').to_euler()

area_light('Key', a + b + up, 700, 3)
area_light('Fill', -a + b + up, 450, 3)

cam_data = bpy.data.cameras.new('Preview Camera')
cam_data.type = 'ORTHO'
cam_data.ortho_scale = max(extents) * 1.23
cam = bpy.data.objects.new('Preview Camera', cam_data)
bpy.context.collection.objects.link(cam)
bpy.context.scene.camera = cam

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 700
scene.render.resolution_y = 700
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.render.film_transparent = True

for i, angle in enumerate((0, 90, 180, 270)):
    theta = math.radians(angle)
    direction = math.cos(theta) * a + math.sin(theta) * b
    cam.location = center + direction * max(2.5, 3 * max(extents)) + up * 0.06
    cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
    scene.render.filepath = str(OUT / f'view_{angle:03d}.png')
    bpy.ops.render.render(write_still=True)
    print('saved', scene.render.filepath, flush=True)

for label, direction in (('top', up), ('bottom', -up)):
    cam.location = center + direction * max(2.5, 3 * max(extents))
    cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam_data.ortho_scale = max(extents[side_axes[0]], extents[side_axes[1]]) * 1.5
    scene.render.filepath = str(OUT / f'view_{label}.png')
    bpy.ops.render.render(write_still=True)
    print('saved', scene.render.filepath, flush=True)

print('mesh bounds', list(mins), list(maxs), 'long axis', long_axis)
