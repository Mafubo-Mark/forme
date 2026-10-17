"""Run inside Blender: render visual-only template 01 review angles."""
from __future__ import annotations

import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main() -> None:
    output = Path(sys.argv[sys.argv.index("--") + 1])
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(output / "template01_ruler_visual.glb"))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(meshes) != 2:
        raise RuntimeError(f"Expected two cover shells, got {len(meshes)}")
    for obj in meshes:
        world_bounds = [obj.matrix_world @ Vector(v) for v in obj.bound_box]
        print("REVIEW_BOUNDS", obj.name, [(min(p[i] for p in world_bounds), max(p[i] for p in world_bounds)) for i in range(3)], flush=True)
    for obj, rgba in zip(sorted(meshes, key=lambda x: x.name),
                         ((.04, .55, .55, 1), (.02, .38, .42, 1))):
        obj.color = rgba
        obj.data.materials.clear()

    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = .001
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "OBJECT"
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = 800
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.display.shading.background_type = "WORLD"
    scene.world.color = (.97, .98, .98)
    cam_data = bpy.data.cameras.new("Concept review camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 420
    camera = bpy.data.objects.new("Concept review camera", cam_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    target = Vector((-8, 5, 180))
    for label, offset in (("front", (0, -850, 30)),
                          ("back", (0, 850, 30)),
                          ("side", (850, 0, 30)),
                          ("three_quarter", (600, -650, 110))):
        camera.location = target + Vector(offset)
        camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(output / f"review_{label}.png")
        bpy.ops.render.render(write_still=True)
    scene["Status"] = "Visual ruler-scaled concept only. Not registered for fit or manufacturing."
    scene["Source"] = "Template 01 祥云 + 200 mm video ruler scaled exploratory envelope"
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "template01_ruler_visual.blend"))


if __name__ == "__main__":
    main()
