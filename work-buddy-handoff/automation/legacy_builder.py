"""Editable Blender cage, shrinkwrap, smoothing, subdivision and solidify cover."""
import bpy, math, json
import numpy as np
from pathlib import Path
from mathutils import Vector

OUT=Path('/Volumes/extra/workspace1/projects/test4/blender-cover-redesign')
SOURCE=Path('/Volumes/extra/workspace1/projects/test4/hunyuan31-v2-comparison/hunyuan31-v2-original.stl')
SCALE=561.1612281171136
ORIGIN=np.array([0,.04,.45])*SCALE
def pt(x,y,z): return Vector(np.array([x,y,z])*SCALE-ORIGIN)

bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene
scene.unit_settings.system='METRIC'; scene.unit_settings.scale_length=.001
scene.unit_settings.length_unit='MILLIMETERS'
bpy.ops.wm.stl_import(filepath=str(SOURCE))
source=bpy.context.object; source.name='01 Reference prosthesis | 120 mm top scale'
coords=np.empty(len(source.data.vertices)*3,dtype=np.float32)
source.data.vertices.foreach_get('co',coords); coords=coords.reshape(-1,3)
native=coords.copy(); coords=coords*SCALE-ORIGIN
source.data.vertices.foreach_set('co',coords.ravel()); source.data.update()
for p in source.data.polygons: p.use_smooth=True

def material(name,color,metal=0):
 m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.use_nodes=True
 bs=m.node_tree.nodes.get('Principled BSDF'); bs.inputs['Base Color'].default_value=(*color,1)
 bs.inputs['Metallic'].default_value=metal; bs.inputs['Roughness'].default_value=.4
 return m
gray=material('Reference warm gray',(.53,.52,.49))
blue=material('Cover satin teal',(.028,.28,.33),.15)
source.data.materials.append(gray); source.color=gray.diffuse_color

# A compact quad cage provides the editable design surface. Its main rings
# are projected onto the supplied mesh by Blender's Shrinkwrap modifier.
nr,na=19,49
# Shoe toe points toward native -Y: lettering is anterior (-Y), gap posterior (+Y).
angles=np.linspace(math.radians(118),math.radians(422),na)
heights=np.linspace(.47,1.065,60)
centers=[]; widths=[]
for z in heights:
 band=native[np.abs(native[:,2]-z)<.008]
 q=np.quantile(band[:,:2],[.02,.98],axis=0)
 centers.append((q[0]+q[1])/2); widths.append((q[1]-q[0])/2)
centers=np.array(centers); widths=np.array(widths)
verts=[]
for iz in range(nr):
 t=iz/(nr-1)
 # Closely spaced end rows preserve the rim after subdivision.
 if iz==1: t=.012
 if iz==nr-2: t=.988
 for theta in angles:
  top=1.020+.037*math.cos(2*theta)
  z=.47+t*(top-.47)
  profile_z=min(z,.96)
  cx=np.interp(profile_z,heights,centers[:,0]); cy=np.interp(profile_z,heights,centers[:,1])
  rx=np.interp(profile_z,heights,widths[:,0]); ry=np.interp(profile_z,heights,widths[:,1])
  flare=max(0,min(1,(z-.87)/.12))
  flare=flare*flare*(3-2*flare)
  margin=.016+.012*flare
  verts.append(pt(cx+(rx+margin)*math.cos(theta),cy+(ry+margin)*math.sin(theta),z))
faces=[]
for iz in range(nr-1):
 for ia in range(na-1):
  a=iz*na+ia; faces.append((a,a+1,a+na+1,a+na))
me=bpy.data.meshes.new('Editable quad control cage'); me.from_pydata(verts,[],faces); me.update()
cover=bpy.data.objects.new('02 COVER | editable Blender modifiers',me); scene.collection.objects.link(cover)
bpy.context.view_layer.objects.active=cover; cover.select_set(True); source.select_set(False)
for p in me.polygons:p.use_smooth=True
cover.data.materials.append(blue); cover.color=blue.diffuse_color
wrap=cover.modifiers.new('01 Fit to original prosthesis (8 mm)','SHRINKWRAP')
wrap.target=source; wrap.wrap_method='NEAREST_SURFACEPOINT'; wrap.wrap_mode='OUTSIDE_SURFACE'; wrap.offset=8
weights=cover.vertex_groups.new(name='Fit body; preserve designed rim')
for iz in range(nr):
 weight=max(0,min(1,(.86-iz/(nr-1))/.12))
 weights.add(list(range(iz*na,(iz+1)*na)),weight,'REPLACE')
wrap.vertex_group=weights.name
smooth=cover.modifiers.new('02 Relax surface irregularities','SMOOTH'); smooth.factor=.7; smooth.iterations=9
sub=cover.modifiers.new('03 Smooth design surface','SUBSURF'); sub.levels=2; sub.render_levels=2
solid=cover.modifiers.new('04 Wall thickness 3 mm','SOLIDIFY'); solid.thickness=3; solid.offset=1; solid.use_even_offset=True

cutters=bpy.data.collections.new('03 Cutters | editable positions and sizes'); scene.collection.children.link(cutters)
def cutter_ellipsoid(name,location,scale):
 bpy.ops.mesh.primitive_uv_sphere_add(segments=48,ring_count=24,location=location)
 obj=bpy.context.object; obj.name=name; obj.scale=scale
 bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
 for c in list(obj.users_collection):c.objects.unlink(obj)
 cutters.objects.link(obj); obj.display_type='WIRE'; obj.hide_render=True
 return obj
def subtract(obj,name):
 mod=cover.modifiers.new(name,'BOOLEAN'); mod.operation='DIFFERENCE'; mod.solver='EXACT'; mod.object=obj

# The cylinder head is at +X. A generous opening avoids reproducing its bump.
bolt=cutter_ellipsoid('Bolt relief | 42 wide x 52 tall',pt(.07,.037,.567),(48,21,26))
subtract(bolt,'05 Bolt access opening')
for theta_deg in (228,312):
 theta=math.radians(theta_deg)
 for k,z in enumerate((.72,.79,.86,.93)):
  cx=np.interp(z,heights,centers[:,0]); cy=np.interp(z,heights,centers[:,1])
  loc=pt(cx+.095*math.cos(theta),cy+.095*math.sin(theta),z)
  cut=cutter_ellipsoid(f'Vent {theta_deg} row {k+1}',loc,(5.2,22,10))
  cut.rotation_euler.z=theta-math.pi/2
  subtract(cut,f'Vent {theta_deg}-{k+1}')

for k,char in enumerate('forme'):
 z=.923-k*.052
 cx=np.interp(z,heights,centers[:,0])
 cy=np.interp(z,heights,centers[:,1])
 ry=np.interp(z,heights,widths[:,1])
 data=bpy.data.curves.new(f'Stencil {char}','FONT'); data.body=char
 data.align_x='CENTER'; data.align_y='CENTER'; data.size=22; data.extrude=20; data.resolution_u=10
 glyph=bpy.data.objects.new(f'Letter {char} cutter',data); scene.collection.objects.link(glyph)
 glyph.location=pt(cx,cy-ry,z); glyph.rotation_euler=(math.pi/2,0,0)
 bpy.ops.object.select_all(action='DESELECT'); glyph.select_set(True); bpy.context.view_layer.objects.active=glyph
 bpy.ops.object.convert(target='MESH'); glyph=bpy.context.object
 if char in 'oe':
  bpy.ops.mesh.primitive_cube_add(size=1,location=glyph.location)
  bridge=bpy.context.object; bridge.name=f'Stencil bridge {char}'
  bridge.scale=(35,70,1.6); bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
  mod=glyph.modifiers.new('Keep island attached by bridge','BOOLEAN'); mod.operation='DIFFERENCE'; mod.solver='EXACT'; mod.object=bridge
  bpy.context.view_layer.objects.active=glyph; bpy.ops.object.modifier_apply(modifier=mod.name)
  bpy.data.objects.remove(bridge,do_unlink=True)
 for c in list(glyph.users_collection):c.objects.unlink(glyph)
 cutters.objects.link(glyph); glyph.display_type='WIRE'; glyph.hide_render=True
 subtract(glyph,f'Stencil forme: {char}')
bevel=cover.modifiers.new('Finish edges 0.65 mm','BEVEL'); bevel.width=.65; bevel.segments=3
bevel.limit_method='ANGLE'; bevel.angle_limit=math.radians(35)
bevel.show_viewport=False; bevel.show_render=False

for obj in cutters.objects:obj.hide_set(True)
source.hide_select=True
cover['Status']='Visual design prototype; physical fit and retention unverified'
cover['Workflow']='Quad cage -> Shrinkwrap original -> Smooth -> Subdivision -> Solidify -> editable Boolean openings'
cover['Units']='mm; local upright model frame, not the earlier registered cloud frame'

scene.render.engine='BLENDER_WORKBENCH'
scene.display.shading.light='STUDIO'; scene.display.shading.color_type='MATERIAL'
scene.display.shading.show_cavity=True; scene.display.shading.cavity_type='BOTH'
scene.display.shading.curvature_ridge_factor=1.2
scene.display.shading.background_type='WORLD'; scene.world.color=(.94,.94,.94)
scene.render.resolution_x=900; scene.render.resolution_y=1100; scene.render.resolution_percentage=100
camd=bpy.data.cameras.new('Review camera'); camd.type='ORTHO'; camd.ortho_scale=390
cam=bpy.data.objects.new('Review camera',camd); scene.collection.objects.link(cam); scene.camera=cam
target=pt(0,.04,.77)
for label,d in [('front',(0,-1,0)),('bolt-side',(1,-.1,0)),('three-quarter',(.8,-1,0)),('rear',(0,1,0))]:
 cam.location=target+Vector(d).normalized()*900+Vector((0,0,35))
 cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
 scene.render.filepath=str(OUT/f'{label}.png'); bpy.ops.render.render(write_still=True)

# Export an evaluated copy; the editable modifier stack stays intact in .blend.
bpy.context.view_layer.update(); deps=bpy.context.evaluated_depsgraph_get()
evaluated=cover.evaluated_get(deps)
export_mesh=bpy.data.meshes.new_from_object(evaluated,depsgraph=deps)
export_obj=bpy.data.objects.new('Export cover',export_mesh); scene.collection.objects.link(export_obj)
bpy.ops.object.select_all(action='DESELECT'); export_obj.select_set(True); bpy.context.view_layer.objects.active=export_obj
bpy.ops.wm.stl_export(filepath=str(OUT/'blender-designed-cover.stl'),export_selected_objects=True)
bpy.data.objects.remove(export_obj,do_unlink=True)
bpy.ops.object.select_all(action='DESELECT'); cover.select_set(True); bpy.context.view_layer.objects.active=cover
for screen in bpy.data.screens:
 for area in screen.areas:
  if area.type=='VIEW_3D':
   space=area.spaces.active; space.shading.type='SOLID'; space.shading.color_type='MATERIAL'
   space.region_3d.view_distance=510; space.region_3d.view_location=target
   space.region_3d.view_rotation=Vector((.7,-1,.08)).to_track_quat('Z','Y')
   space.region_3d.view_perspective='ORTHO'
scene['Design status']='Blender shape review; fixed hardware and physical clearance still require validation'
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'blender-cover-redesign.blend'))
print('Saved editable Blender design and evaluated STL',flush=True)
