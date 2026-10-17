"""Render two inspection views of the provisional test4 STL with Blender."""
import bpy
from mathutils import Vector
from pathlib import Path
import os
import json
import math

base = Path(os.environ.get('COVER_RENDER_DIR', '/Volumes/extra/workspace1/projects/test4/cad-prototype'))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.wm.stl_import(filepath=str(base / os.environ.get('COVER_MESH_FILE', 'fitted_c_cover.stl')))
shell = bpy.context.object
shell.name = 'Provisional fitted cover'
mat = bpy.data.materials.new('Teal shell')
mat.diffuse_color = (0.10, 0.46, 0.53, 1)
shell.data.materials.append(mat)

cam_data = bpy.data.cameras.new('Inspection camera')
camera = bpy.data.objects.new('Inspection camera', cam_data)
bpy.context.collection.objects.link(camera)
bpy.context.scene.camera = camera
cam_data.type = 'ORTHO'
cam_data.ortho_scale = 460

scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = 850
scene.render.resolution_y = 1050
scene.render.resolution_percentage = 100
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'MATERIAL'
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = 'BOTH'
scene.display.shading.show_shadows = True
scene.render.image_settings.file_format = 'PNG'
target = Vector((0, 0, 180))
sections_path = base / 'sections.json'
angle = math.radians(float(os.environ.get('COVER_OPENING_CENTER_DEG',
    json.loads(sections_path.read_text()).get('opening_center_deg', 90) if sections_path.exists() else 90)))
opening_camera = (610*math.cos(angle), 610*math.sin(angle), 280)
bolt_camera = (-610*math.cos(angle), -610*math.sin(angle), 280)

for name, location in [
    ('cover-bolt-side.png', bolt_camera),
    ('cover-opening-side.png', opening_camera),
]:
    camera.location = location
    camera.rotation_euler = (target - camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.render.filepath = str(base / name)
    bpy.ops.render.render(write_still=True)
