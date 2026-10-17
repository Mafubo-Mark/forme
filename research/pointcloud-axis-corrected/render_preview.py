"""Render inspection views of the generated STL with Blender Workbench."""

from pathlib import Path

import bpy
from mathutils import Vector


here = Path(__file__).resolve().parent
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.wm.stl_import(filepath=str(here / "fitted_c_cover.stl"))
cover = bpy.context.object
cover.name = "Point cloud loft cover | geometry demo"
cover.color = (0.04, 0.50, 0.52, 1.0)

camera_data = bpy.data.cameras.new("Inspection camera")
camera = bpy.data.objects.new("Inspection camera", camera_data)
bpy.context.collection.objects.link(camera)
bpy.context.scene.camera = camera
camera_data.type = "ORTHO"
camera_data.ortho_scale = 430

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "OBJECT"
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.render.resolution_x = 900
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.world.color = (0.16, 0.18, 0.20)

target = Vector((0, 0, 137.5))
for name, location in (
    ("preview-oblique.png", Vector((420, -540, 330))),
    ("preview-opening.png", Vector((0, 620, 175))),
):
    camera.location = location
    camera.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(here / name)
    bpy.ops.render.render(write_still=True)
