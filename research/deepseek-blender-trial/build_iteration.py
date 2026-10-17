"""Deterministic Blender builder for the DeepSeek visual feedback loop.

Run with Blender: blender -b base_scene.blend --python build_iteration.py -- spec.json output_dir
The JSON is numeric only. No model-generated Python is executed.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


spec_path, output_path = map(Path, sys.argv[sys.argv.index("--") + 1:][:2])
spec = json.loads(spec_path.read_text(encoding="utf-8"))
output_path.mkdir(parents=True, exist_ok=True)

source = bpy.data.objects["01 Reference prosthesis | 120 mm top scale"]
cage = bpy.data.objects["02 Editable design cage | hidden | enable to change modifiers"]
old_cover = bpy.data.objects.get("00 COVER | cleaned final design")
if old_cover:
    old_cover.hide_render = True
    old_cover.hide_set(True)
cage.hide_render = True
cage.hide_set(True)

shell = cage.copy()
shell.data = cage.data.copy()
bpy.context.scene.collection.objects.link(shell)
shell.name = "DS Auto | protective shell"
shell.hide_render = False
shell.hide_set(False)
shell.color = (0.02, 0.39, 0.47, 1)
source.color = (0.62, 0.61, 0.58, 1)

# Preserve the proven body fit and bolt cut, while removing decorative cutouts.
for modifier in list(shell.modifiers):
    if modifier.type == "BOOLEAN" and not modifier.name.startswith("05 Bolt"):
        shell.modifiers.remove(modifier)
    elif modifier.type == "BEVEL":
        shell.modifiers.remove(modifier)

wrap = next((m for m in shell.modifiers if m.type == "SHRINKWRAP"), None)
smooth = next((m for m in shell.modifiers if m.type == "SMOOTH"), None)
solid = next((m for m in shell.modifiers if m.type == "SOLIDIFY"), None)
if wrap:
    wrap.offset = float(spec["clearance_mm"])
if smooth:
    smooth.iterations = int(spec["smooth_iterations"])
if solid:
    solid.thickness = float(spec["wall_mm"])

nr, na = 19, 49
assert len(shell.data.vertices) == nr * na
profile = spec["profile_mm"]
for iz in range(nr):
    # The original control cage has densely spaced end rings. Keep its geometry.
    t = iz / (nr - 1)
    row = [shell.data.vertices[iz * na + ia] for ia in range(na)]
    cx = sum(v.co.x for v in row) / na
    cy = sum(v.co.y for v in row) / na
    f = t * (len(profile) - 1)
    lo = min(len(profile) - 2, int(f))
    radial_mm = profile[lo] * (1 - (f - lo)) + profile[lo + 1] * (f - lo)
    upper = max(0.0, (t - 0.75) / 0.25)
    upper = upper * upper * (3 - 2 * upper)
    for v in row:
        dx, dy = v.co.x - cx, v.co.y - cy
        angle = math.atan2(dy, dx)
        r = max(1e-6, math.hypot(dx, dy))
        # A smooth per-height profile. No high-frequency angular ripples.
        dr = radial_mm + upper * float(spec["upper_flare_mm"])
        dr += float(spec["front_back_bias_mm"]) * math.cos(angle - math.pi / 2) * (0.3 + 0.7 * upper)
        v.co.x += dr * dx / r
        v.co.y += dr * dy / r
        # Upper rim follows the original asymmetric cage; adjust its height smoothly.
        v.co.z += upper * (
            float(spec["upper_raise_mm"])
            + float(spec["rim_asymmetry_mm"]) * math.cos(angle - math.pi / 4)
        )
shell.data.update()

for obj in bpy.data.objects:
    if obj.name.startswith(("Bolt relief", "Vent ", "Letter ", "Stencil ")):
        obj.hide_render = True
        obj.display_type = "WIRE"

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "OBJECT"
scene.display.shading.show_cavity = True
scene.display.shading.background_type = "WORLD"
scene.world.color = (0.94, 0.94, 0.94)
scene.render.resolution_x = 700
scene.render.resolution_y = 850
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"

camera = bpy.data.objects.get("Review camera")
if camera is None or camera.type != "CAMERA":
    data = bpy.data.cameras.new("DS Auto camera")
    camera = bpy.data.objects.new("DS Auto camera", data)
    scene.collection.objects.link(camera)
scene.camera = camera
camera.data.type = "ORTHO"
camera.data.ortho_scale = 395
camera.data.clip_end = 2000
target = Vector((0, 0, 185))
for label, direction in [
    ("front", Vector((0, -1, 0))),
    ("rear", Vector((0, 1, 0))),
    ("bolt_side", Vector((1, -0.1, 0))),
    ("three_quarter", Vector((0.8, -1, 0.14))),
]:
    camera.location = target + direction.normalized() * 850
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(output_path / (label + ".png"))
    bpy.ops.render.render(write_still=True)

bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
mesh = bpy.data.meshes.new_from_object(shell.evaluated_get(deps), depsgraph=deps)
export_obj = bpy.data.objects.new("DS Auto export", mesh)
scene.collection.objects.link(export_obj)
bpy.ops.object.select_all(action="DESELECT")
export_obj.select_set(True)
bpy.context.view_layer.objects.active = export_obj
bpy.ops.wm.stl_export(filepath=str(output_path / "shell.stl"), export_selected_objects=True)
bpy.data.objects.remove(export_obj, do_unlink=True)

import bmesh
bm = bmesh.new()
bm.from_mesh(mesh)
boundary_edges = sum(1 for edge in bm.edges if edge.is_boundary)
nonmanifold_edges = sum(1 for edge in bm.edges if not edge.is_manifold)
unseen = set(bm.verts)
components = 0
while unseen:
    components += 1
    stack = [unseen.pop()]
    while stack:
        current = stack.pop()
        for edge in current.link_edges:
            neighbor = edge.other_vert(current)
            if neighbor in unseen:
                unseen.remove(neighbor)
                stack.append(neighbor)
bm.free()
z_values = [v.co.z for v in mesh.vertices]
metrics = {
    "vertices": len(mesh.vertices),
    "faces": len(mesh.polygons),
    "boundary_edges": boundary_edges,
    "nonmanifold_edges": nonmanifold_edges,
    "components": components,
    "z_min_mm": round(min(z_values), 2),
    "z_max_mm": round(max(z_values), 2),
    "height_mm": round(max(z_values) - min(z_values), 2),
    "watertight": boundary_edges == 0 and nonmanifold_edges == 0 and components == 1,
}
(output_path / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
bpy.ops.wm.save_as_mainfile(filepath=str(output_path / "review.blend"))
print("DS_AUTO_METRICS " + json.dumps(metrics), flush=True)
