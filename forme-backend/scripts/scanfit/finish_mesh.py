"""Blender booleans with the same anchored rim and finite bolt opening as V5."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector
O=Path(sys.argv[sys.argv.index('--')+1]).resolve();cfg=json.loads((O/'run_config.json').read_text());bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=str(O/'rim_limit_volume.stl'));limit=bpy.context.object
bolt=cfg['bolt'];base=Vector(bolt['baseMm']);axis=Vector(bolt['axis']);bpy.ops.mesh.primitive_cylinder_add(vertices=128,radius=bolt['diameterMm']/2,depth=70,location=base+axis*20);cut=bpy.context.object;cut.rotation_euler=axis.to_track_quat('Z','Y').to_euler()
for side in ['front','rear']:
 p=O/f'cover_{side}_mm.stl';bpy.ops.wm.stl_import(filepath=str(p));ob=bpy.context.object
 for operation,obj in [('INTERSECT',limit),('DIFFERENCE',cut)]:
  mod=ob.modifiers.new(operation,'BOOLEAN');mod.operation=operation;mod.solver='EXACT';mod.object=obj;bpy.context.view_layer.objects.active=ob;bpy.ops.object.modifier_apply(modifier=mod.name)
 bpy.ops.object.select_all(action='DESELECT');ob.select_set(True);bpy.context.view_layer.objects.active=ob;bpy.ops.wm.stl_export(filepath=str(p),export_selected_objects=True);bpy.data.objects.remove(ob,do_unlink=True)
