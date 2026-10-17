import bpy
from pathlib import Path
p=Path('/Volumes/extra/workspace1/projects/test4/blender-cover-redesign')
design=bpy.data.objects['02 COVER | editable Blender modifiers']
design.hide_set(True);design.hide_render=True
design.name='02 Editable design cage | hidden | enable to change modifiers'
bpy.ops.wm.stl_import(filepath=str(p/'blender-designed-cover.stl'))
cover=bpy.context.object;cover.name='00 COVER | cleaned final design'
cover.data.materials.append(bpy.data.materials['Cover satin teal'])
for face in cover.data.polygons:face.use_smooth=True
cover['Source']='Blender editable cage 02; final evaluated mesh with zero-volume duplicate triangles removed'
cover['Status']='One closed solid; physical fit and mounting unverified'
bpy.context.view_layer.objects.active=cover
bpy.ops.wm.save_as_mainfile(filepath=str(p/'blender-cover-redesign.blend'))
