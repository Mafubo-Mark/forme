"""Sample shell thickness by casting inward rays against each STL's BVH.

Run with Blender -b -P inspect_print_mesh.py -- front.stl rear.stl output.json
"""
import bpy
import json
import math
import random
import sys

from mathutils import Vector
from mathutils.bvhtree import BVHTree


args = sys.argv[sys.argv.index("--") + 1:]
paths, output_path = args[:-1], args[-1]
results = []
for path in paths:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.stl_import(filepath=path)
    obj = next(o for o in bpy.data.objects if o.type == "MESH")
    mesh = obj.data
    mesh.calc_loop_triangles()
    tree = BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())
    rng = random.Random(20261004)
    sample_count = min(12000, len(mesh.polygons))
    sample_idxs = rng.sample(range(len(mesh.polygons)), sample_count)
    samples = []
    missing = 0
    for index in sample_idxs:
        poly = mesh.polygons[index]
        normal = poly.normal.normalized()
        if normal.length < 0.9:
            continue
        point = poly.center
        # Begin just inside the shell to avoid a self-hit on the source face.
        start = point - normal * 0.04
        thickness = None
        traveled = 0.04
        # A ray can first touch an adjacent facet in a carved pattern. Continue
        # until it reaches a face oriented against the source surface.
        for _ in range(8):
            hit, hit_normal, face, distance = tree.ray_cast(start, -normal, 20.0 - traveled)
            if hit is None or distance is None:
                break
            traveled += distance
            if hit_normal.normalized().dot(normal) < -0.5:
                thickness = traveled
                break
            start = hit - normal * 0.04
            traveled += 0.04
        if thickness is None:
            missing += 1
            continue
        if 0.06 < thickness < 20.0:
            samples.append((float(thickness), [float(v) for v in point], [float(v) for v in normal]))
    values = sorted(v for v, _, _ in samples)
    def percentile(p):
        if not values:
            return None
        return values[min(len(values)-1, int((len(values)-1)*p/100))]
    results.append({
        "path": path,
        "faces": len(mesh.polygons),
        "samplesAttempted": sample_count,
        "samplesWithHit": len(samples),
        "samplesWithoutHit": missing,
        "thicknessMm": {"min": percentile(0), "p01": percentile(1),
                        "p05": percentile(5), "median": percentile(50),
                        "p95": percentile(95)},
        "sampledBelow1_2Mm": sum(v < 1.2 for v in values),
        "sampledBelow1_6Mm": sum(v < 1.6 for v in values),
        "thinnestSampleLocations": sorted(samples)[:12],
    })
with open(output_path, "w") as handle:
    json.dump({"method": "inward face-normal BVH raycast; sampled estimate, not exact minimum wall", "parts": results}, handle, indent=2)
print(json.dumps([{"path": p["path"], "thicknessMm": p["thicknessMm"],
                   "below1_2": p["sampledBelow1_2Mm"]} for p in results]))
