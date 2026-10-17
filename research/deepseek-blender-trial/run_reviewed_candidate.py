"""Run the manually reviewed DeepSeek v2 code on a copied Blender scene."""

import bpy
from pathlib import Path
from mathutils import Vector


HERE = Path(__file__).resolve().parent
CODE = HERE / "candidate_blender_v2_run.py"
exec(compile(CODE.read_text(encoding="utf-8"), str(CODE), "exec"), {"__name__": "__main__"})

shell = bpy.data.objects["DS Trial Shell"]
reference = bpy.data.objects["01 Reference prosthesis | 120 mm top scale"]

for name in ["00 COVER | cleaned final design", "02 Editable design cage | hidden | enable to change modifiers"]:
    obj = bpy.data.objects.get(name)
    if obj is not None:
        obj.hide_render = True
        obj.hide_set(True)

for obj in bpy.data.objects:
    if obj.name.startswith("DS Trial Bolt relief cutter"):
        obj.hide_render = True
        obj.display_type = "WIRE"

shell.color = (0.02, 0.36, 0.48, 1.0)
reference.color = (0.58, 0.57, 0.55, 1.0)
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "OBJECT"
scene.display.shading.show_cavity = True
scene.display.shading.background_type = "WORLD"
scene.world.color = (0.94, 0.94, 0.94)
scene.render.resolution_x = 1000
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100

cam = bpy.data.objects.get("Review camera")
if cam is None or cam.type != "CAMERA":
    cam_data = bpy.data.cameras.new("DS Trial camera")
    cam = bpy.data.objects.new("DS Trial camera", cam_data)
    scene.collection.objects.link(cam)
cam.data.type = "ORTHO"
scene.camera = cam
center = sum((reference.matrix_world @ Vector(c) for c in reference.bound_box), Vector()) / 8.0
height = max((reference.matrix_world @ Vector(c)).z for c in reference.bound_box) - min((reference.matrix_world @ Vector(c)).z for c in reference.bound_box)
cam.data.ortho_scale = height * 1.3
cam.data.clip_end = height * 10.0

for label, direction in [
    ("front", Vector((0, -1, 0))),
    ("rear", Vector((0, 1, 0))),
    ("bolt_side", Vector((1, 0, 0))),
    ("three_quarter", Vector((1, -1, 0))),
]:
    cam.location = center + direction.normalized() * (height * 3.0) + Vector((0, 0, height * 0.08))
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(HERE / f"v2_{label}.png")
    bpy.ops.render.render(write_still=True)

deps = bpy.context.evaluated_depsgraph_get()
evaluated = shell.evaluated_get(deps)
mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=deps)
export_obj = bpy.data.objects.new("DS Trial export", mesh)
scene.collection.objects.link(export_obj)
bpy.ops.object.select_all(action="DESELECT")
export_obj.select_set(True)
bpy.context.view_layer.objects.active = export_obj
bpy.ops.wm.stl_export(filepath=str(HERE / "v2_shell.stl"), export_selected_objects=True)
bpy.data.objects.remove(export_obj, do_unlink=True)

bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "v2_review.blend"))
print("DS Trial evaluated mesh:", len(mesh.vertices), "vertices", len(mesh.polygons), "faces", flush=True)
