"""Render four inspection views in Blender's CPU Cycles engine."""
from pathlib import Path
import math
import sys

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
stem = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "alpha4-offset1p5-smooth3"
MESH = HERE / f"{stem}.off"

with MESH.open() as f:
    assert f.readline().strip() == "OFF"
    nv, nf, _ = map(int, f.readline().split())
    verts = [tuple(map(float, f.readline().split())) for _ in range(nv)]
    faces = []
    for _ in range(nf):
        row = list(map(int, f.readline().split()))
        faces.append(tuple(row[1:]))
mid_z = (min(v[2] for v in verts) + max(v[2] for v in verts)) / 2
height = max(v[2] for v in verts) - min(v[2] for v in verts)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
mesh = bpy.data.meshes.new("Measured-envelope-draft")
mesh.from_pydata(verts, [], faces)
mesh.update()
obj = bpy.data.objects.new("Smoothed CGAL reference mesh", mesh)
bpy.context.collection.objects.link(obj)
for poly in mesh.polygons:
    poly.use_smooth = True
mat = bpy.data.materials.new("neutral polymer")
mat.diffuse_color = (0.24, 0.42, 0.51, 1)
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (0.18, 0.37, 0.48, 1)
bsdf.inputs["Roughness"].default_value = 0.82
obj.data.materials.append(mat)

world = bpy.data.worlds.new("white studio")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes.get("Background").inputs["Color"].default_value = (1, 1, 1, 1)
world.node_tree.nodes.get("Background").inputs["Strength"].default_value = 0.8

def area(name, location, energy, size):
    light = bpy.data.lights.new(name, "AREA")
    light.energy = energy
    light.shape = "DISK"
    light.size = size
    o = bpy.data.objects.new(name, light)
    bpy.context.collection.objects.link(o)
    o.location = location
    o.rotation_euler = (Vector((0, 0, mid_z)) - o.location).to_track_quat("-Z", "Y").to_euler()

area("key", (240, -180, 400), 500, 350)
area("fill", (-250, 200, 320), 350, 450)

cam_data = bpy.data.cameras.new("inspection camera")
cam = bpy.data.objects.new("inspection camera", cam_data)
bpy.context.collection.objects.link(cam)
bpy.context.scene.camera = cam
cam_data.type = "ORTHO"
cam_data.ortho_scale = height * 1.18

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 16
scene.render.resolution_x = 480
scene.render.resolution_y = 800
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False

for deg in (0, 90, 180, 270):
    angle = math.radians(deg)
    cam.location = (650 * math.sin(angle), -650 * math.cos(angle), mid_z + 135)
    cam.rotation_euler = (Vector((0, 0, mid_z)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(HERE / f"{stem}-preview-{deg:03d}.png")
    bpy.ops.render.render(write_still=True)
