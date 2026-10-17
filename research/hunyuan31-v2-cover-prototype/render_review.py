"""Render the trial cover together with the scaled prosthesis mesh in Blender."""

import math
from pathlib import Path

import bpy
from mathutils import Vector
import json

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
OUT = ROOT/'hunyuan31-v2-cover-prototype'
ALIGNED = ROOT/'hunyuan31-v2-comparison/hunyuan31-v2-aligned-mm.stl'
REP = json.loads((ROOT/'hunyuan31-v2-comparison/comparison-report.json').read_text())
best = REP['best']
scale = best['scale_mm_per_stl_unit']
R = best['R']
T = best['translation_mm']

def transformed(native):
    return Vector(tuple(scale*sum(R[i][j]*native[j] for j in range(3))+T[i]
                        for i in range(3)))

def direction(native):
    return Vector(tuple(sum(R[i][j]*native[j] for j in range(3))
                        for i in range(3)))

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.wm.stl_import(filepath=str(ALIGNED))
source = bpy.context.object
source.name = 'Reference AI prosthesis | scaled and registered | shoe/hand artifacts remain'
bpy.ops.wm.stl_import(filepath=str(OUT/'cover_trial.stl'))
cover = bpy.context.object
cover.name = 'Provisional protective C cover | 8 mm clearance | 3 mm wall'

for obj, color in [(source, (.73, .72, .68, 1)),
                   (cover, (.02, .37, .83, 1))]:
    obj.color = color
    m = bpy.data.materials.new(obj.name+' material')
    m.diffuse_color = color
    m.use_nodes = True
    node = m.node_tree.nodes.get('Principled BSDF')
    node.inputs['Base Color'].default_value = color
    node.inputs['Roughness'].default_value = .75
    obj.data.materials.clear()
    obj.data.materials.append(m)

scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = .001
scene.unit_settings.length_unit = 'MILLIMETERS'
scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'OBJECT'
scene.display.shading.show_cavity = True
scene.render.resolution_x = 850
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.display.shading.background_type = 'WORLD'
scene.world.color = (.98, .98, .98)

camera_data = bpy.data.cameras.new('Orthographic review camera')
camera_data.type = 'ORTHO'
camera_data.ortho_scale = 410
camera = bpy.data.objects.new('Orthographic review camera', camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
target = transformed((0.0, 0.035, .77))
up = direction((0, 0, 1))

for name, native in [('front', (0, 1, 0)), ('side', (1, 0, 0)),
                     ('back', (0, -1, 0))]:
    eye = target + direction(native)*900 + up*35
    camera.location = eye
    camera.rotation_euler = (target-eye).to_track_quat('-Z', 'Y').to_euler()
    scene.render.filepath = str(OUT/f'cover-on-model-{name}.png')
    bpy.ops.render.render(write_still=True)
    source.hide_render = True
    scene.render.filepath = str(OUT/f'cover-only-{name}.png')
    bpy.ops.render.render(write_still=True)
    source.hide_render = False

source.display_type = 'WIRE'
source.show_in_front = True
cover.display_type = 'SOLID'
bpy.ops.object.select_all(action='DESELECT')
cover.select_set(True)
bpy.context.view_layer.objects.active = cover
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        space = area.spaces.active
        space.shading.type = 'SOLID'
        space.shading.color_type = 'OBJECT'
        space.region_3d.view_perspective = 'ORTHO'
        space.region_3d.view_location = target
        space.region_3d.view_distance = 540
        space.region_3d.view_rotation = camera.rotation_euler.to_quaternion()
scene['Status'] = 'Visual fit prototype only; clearance to AI mesh is not clearance to physical prosthesis.'
scene['Source mesh'] = str(ALIGNED)
scene['Cover settings'] = '8 mm nominal clearance, 3 mm wall, 72 degree side opening'
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'cover-fit-review.blend'))
print('Saved cover review scene and preview images', flush=True)
