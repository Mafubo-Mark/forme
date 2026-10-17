import bpy,json,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import sys
O=Path(sys.argv[sys.argv.index('--')+1]).resolve();bpy.ops.wm.read_factory_settings(use_empty=True);data=json.loads((O/'run_config.json').read_text());base=Vector(data['bolt']['baseMm']);axis=Vector(data['bolt']['axis']);u=axis.cross(Vector((0,0,1))).normalized();v=axis.cross(u);result={}
for side in ['front','rear']:
 bpy.ops.wm.stl_import(filepath=str(O/f'cover_{side}_mm.stl'));ob=bpy.context.object;tree=BVHTree.FromPolygons([v.co[:] for v in ob.data.vertices],[p.vertices[:] for p in ob.data.polygons],all_triangles=True);hits=[];count=0
 for radius in [0]+[data['bolt']['diameterMm']/2*f for f in [.25,.5,.75,.95]]:
  for k in range(36 if radius else 1):
   a=2*math.pi*k/36;start=base-axis*15+radius*(u*math.cos(a)+v*math.sin(a));hit=tree.ray_cast(start,axis,70);count+=1
   if hit[0] is not None:hits.append({'radiusMm':radius,'angleIndex':k,'hitMm':list(hit[0])})
 result[side]={'sampledAxialSegments':count,'blockedSegments':len(hits),'hits':hits};assert not hits,result[side];bpy.data.objects.remove(ob,do_unlink=True)
(O/'bolt_clearance_review.json').write_text(json.dumps({'method':'finite axial rays across 70 mm bolt channel at center and .25/.5/.75/.95 of configured hole radius; verifies mesh channel, not real bolt measurement','parts':result},indent=2));print(result)
