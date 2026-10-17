"""Cut short fit samples from the editable Blender cover at three offsets."""

from pathlib import Path
import bpy

ROOT = Path('/Volumes/extra/workspace1/projects/test4/blender-cover-redesign')
OUT = ROOT / 'fit-coupons'
OUT.mkdir(exist_ok=True)

design = bpy.data.objects['02 Editable design cage | hidden | enable to change modifiers']
wrap = design.modifiers['01 Fit to original prosthesis (8 mm)']
design.hide_set(False)
design.hide_render = False

# The user's 80 mm left-right measurement was taken about 30 mm below the
# transition band. In this upright Blender frame, that is near z = 82.2 mm.
coupon_center_z_mm = (.65 - 30.0/561.1612281171136 - .45) * 561.1612281171136
coupon_height_mm = 25.0
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, coupon_center_z_mm))
slab = bpy.context.object
slab.name = 'Coupon crop slab 25 mm high'
slab.scale = (400, 400, coupon_height_mm)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
slab.hide_render = True
halves = []
for label, center_x in [('left', -150), ('right', 150)]:
    bpy.ops.mesh.primitive_cube_add(size=1, location=(center_x, 0, coupon_center_z_mm))
    half = bpy.context.object
    half.name = f'Coupon {label} half volume'
    half.scale = (300, 400, 100)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    half.hide_render = True
    halves.append((label, half))

for offset in (4.0, 6.0, 8.0):
    wrap.offset = offset
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    for label, half in halves:
        mesh = bpy.data.meshes.new_from_object(design.evaluated_get(deps), depsgraph=deps)
        part = bpy.data.objects.new(f'Coupon {offset:g} mm {label}', mesh)
        bpy.context.scene.collection.objects.link(part)
        for cutter, desc in [(slab, '25 mm shaft segment'), (half, 'PLA side half')]:
            crop = part.modifiers.new(f'Keep {desc}', 'BOOLEAN')
            crop.operation = 'INTERSECT'
            crop.solver = 'EXACT'
            crop.object = cutter
            bpy.ops.object.select_all(action='DESELECT')
            part.select_set(True)
            bpy.context.view_layer.objects.active = part
            bpy.ops.object.modifier_apply(modifier=crop.name)
        bpy.ops.wm.stl_export(
            filepath=str(OUT / f'fit-coupon-offset-{offset:g}mm-{label}.stl'),
            export_selected_objects=True,
        )
        bpy.data.objects.remove(part, do_unlink=True)

bpy.data.objects.remove(slab, do_unlink=True)
for _, half in halves:
    bpy.data.objects.remove(half, do_unlink=True)
print('Exported fit coupons around z=', coupon_center_z_mm, flush=True)
