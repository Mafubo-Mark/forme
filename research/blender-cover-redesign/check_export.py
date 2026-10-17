import bpy
from pathlib import Path
p=Path('/Volumes/extra/workspace1/projects/test4/blender-cover-redesign')
c=bpy.data.objects['02 COVER | editable Blender modifiers']
c.modifiers['Finish edges 0.65 mm'].show_viewport=False
c.modifiers['Finish edges 0.65 mm'].show_render=False
bpy.context.view_layer.update()
deps=bpy.context.evaluated_depsgraph_get()
mesh=bpy.data.meshes.new_from_object(c.evaluated_get(deps),depsgraph=deps)
o=bpy.data.objects.new('check',mesh);bpy.context.scene.collection.objects.link(o)
bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o
bpy.ops.wm.stl_export(filepath=str(p/'no-bevel-check.stl'),export_selected_objects=True)
