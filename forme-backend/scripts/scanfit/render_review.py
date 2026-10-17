import bpy,math,json
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from pathlib import Path
import sys
out=Path(sys.argv[sys.argv.index('--')+1]).resolve();cfg=json.loads((out/'run_config.json').read_text());(out/'fit_coupons').mkdir(exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
parts={}
for side in ['front','rear']:
 bpy.ops.wm.stl_import(filepath=str(out/f'cover_{side}_mm.stl'));parts[side]=bpy.context.object
# BVH overlap reports pairs of potentially intersecting triangles, retained as review evidence.
def tree(ob):return BVHTree.FromPolygons([v.co[:] for v in ob.data.vertices],[p.vertices[:] for p in ob.data.polygons],all_triangles=True,epsilon=0.0)
trees={side:tree(ob) for side,ob in parts.items()};intersections=trees['front'].overlap(trees['rear']);(out/'seam_bvh_review.json').write_text(json.dumps({'triangleOverlapPairCount':len(intersections),'firstPairs':intersections[:20],'method':'Blender BVH overlap between front and rear in assembled coordinates; contact/tolerance and fastening movement not validated'},indent=2));print('OVERLAP',len(intersections),flush=True)
# Sample inward-normal ray thickness; not a certified minimum wall test.
import random
random.seed(1610);thickness={}
for side,ob in parts.items():
 values=[]
 for poly in random.sample(list(ob.data.polygons),min(3000,len(ob.data.polygons))):
  normal=poly.normal;hit,_,_,distance=trees[side].ray_cast(poly.center-normal*.01,-normal,12.)
  if hit is not None:values.append(distance+.01)
 values.sort()
 thickness[side]={'sampledFaceCount':3000,'rayHitCount':len(values),'minMm':values[0] if values else None,'p01Mm':values[int(len(values)*.01)] if values else None,'medianMm':values[len(values)//2] if values else None,'sampleCountBelow1_2Mm':sum(v<1.2 for v in values),'method':'uniform face sample inward-normal BVH raycast; holes, ribs and seams affect results; not true minimum wall proof'}
(out/'wall_thickness_review.json').write_text(json.dumps(thickness,indent=2))
for side,original in parts.items():
 for z in [float(cfg['bolt']['baseMm'][2])]:
  ob=original.copy();ob.data=original.data.copy();bpy.context.collection.objects.link(ob)
  bpy.ops.mesh.primitive_cube_add(size=2,location=(0,24,z));box=bpy.context.object;box.scale=(200,200,35);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
  mod=ob.modifiers.new('70mm fit slice','BOOLEAN');mod.operation='INTERSECT';mod.solver='EXACT';mod.object=box;bpy.context.view_layer.objects.active=ob;bpy.ops.object.modifier_apply(modifier=mod.name);bpy.data.objects.remove(box,do_unlink=True)
  for v in ob.data.vertices:v.co.z-=z-35
  bpy.ops.object.select_all(action='DESELECT');ob.select_set(True);bpy.context.view_layer.objects.active=ob;bpy.ops.wm.stl_export(filepath=str(out/'fit_coupons'/f'{side}_z{z}_70mm.stl'),export_selected_objects=True);bpy.data.objects.remove(ob,do_unlink=True)
  print('COUPON',side,z,flush=True)
scene=bpy.context.scene
for side,ob in parts.items():
 ob.scale=(.001,)*3;mat=bpy.data.materials.new(side);mat.diffuse_color=(.12,.32,.4,1) if side=='front' else (.25,.43,.33,1);ob.data.materials.append(mat)
scene.render.engine='BLENDER_WORKBENCH';scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL';scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True;scene.display.shading.cavity_type='BOTH';scene.display.shading.background_type='WORLD';scene.world=bpy.data.worlds.new('Review world');scene.world.color=(.9,.92,.9);scene.render.film_transparent=False;scene.render.resolution_x=650;scene.render.resolution_y=850;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
bpy.ops.object.camera_add();cam=bpy.context.object;scene.camera=cam;cam.data.type='ORTHO';cam.data.ortho_scale=.46
for name,loc in [('front',(.35,-.65,.34)),('rear',(-.35,.65,.34)),('side',(.65,.12,.13)),('top',(.12,.024,.8))]:
 cam.location=loc;cam.rotation_euler=(Vector((0,.024,.125))-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=str(out/f'preview_{name}.png');bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'candidate_review.blend'))
