"""Create lightweight public GLB previews from registered template STLs.

Run with Blender: blender -b -t 2 --python scripts/build_template_previews.py
The decimated meshes are for product selection only, never manufacturing.
"""

import shutil
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[2] / "work-buddy-handoff" / "templates"
OUT = Path(__file__).resolve().parents[1] / "web" / "assets" / "templates"
OUT.mkdir(parents=True, exist_ok=True)

for template_id in ("01", "02", "03", "04", "05", "06", "05-magnetic"):
    source = ROOT / template_id
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    filenames = ("front.stl", "rear.stl") if template_id != "05-magnetic" else ("前壳.stl", "后壳.stl")
    for filename in filenames:
        path = source / filename
        try:
            bpy.ops.wm.stl_import(filepath=str(path))
        except AttributeError:
            bpy.ops.import_mesh.stl(filepath=str(path))
        mesh = bpy.context.object
        mesh.name = filename.removesuffix(".stl")
        modifier = mesh.modifiers.new("Web preview only", "DECIMATE")
        modifier.ratio = 0.07
        bpy.context.view_layer.objects.active = mesh
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        material = bpy.data.materials.new(name="Preview color")
        material.diffuse_color = (0.76, 0.79, 0.77, 1.0)
        material.use_nodes = True
        material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (0.76, 0.79, 0.77, 1.0)
        mesh.data.materials.append(material)
    target = OUT / f"{template_id}.glb"
    bpy.ops.export_scene.gltf(filepath=str(target), export_format="GLB", export_apply=True)
    hero = source / ("hero.png" if template_id != "05-magnetic" else "整体.png")
    shutil.copyfile(hero, OUT / f"{template_id}.png")
    print(f"preview {template_id}: {target.stat().st_size} bytes")
