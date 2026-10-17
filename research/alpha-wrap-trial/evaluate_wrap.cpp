#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/IO/polygon_mesh_io.h>
#include <CGAL/AABB_tree.h>
#include <CGAL/AABB_traits_3.h>
#include <CGAL/AABB_face_graph_triangle_primitive.h>
#include <CGAL/Side_of_triangle_mesh.h>
#include <fstream>
#include <iostream>
#include <cmath>

using K=CGAL::Exact_predicates_inexact_constructions_kernel;
using P=K::Point_3;
using M=CGAL::Surface_mesh<P>;
using Primitive=CGAL::AABB_face_graph_triangle_primitive<M>;
using Traits=CGAL::AABB_traits_3<K,Primitive>;
using Tree=CGAL::AABB_tree<Traits>;

int main(int argc,char** argv){
  if(argc!=4){std::cerr<<"usage: evaluate_wrap wrap.off points.xyz output.csv\n";return 2;}
  M mesh;
  if(!CGAL::IO::read_polygon_mesh(argv[1],mesh)){std::cerr<<"mesh read failed\n";return 2;}
  Tree tree(faces(mesh).first,faces(mesh).second,mesh);
  tree.accelerate_distance_queries();
  CGAL::Side_of_triangle_mesh<M,K> side(mesh);
  std::ifstream in(argv[2]);std::ofstream out(argv[3]);
  if(!in||!out){std::cerr<<"file open failed\n";return 2;}
  out<<"x,y,z,signed_gap_mm\n";
  double x,y,z;size_t n=0;
  while(in>>x>>y>>z){
    P p(x,y,z);
    double d=std::sqrt(CGAL::to_double(tree.squared_distance(p)));
    auto s=side(p);
    if(s==CGAL::ON_UNBOUNDED_SIDE)d=-d;
    if(s==CGAL::ON_BOUNDARY)d=0;
    out<<x<<","<<y<<","<<z<<","<<d<<"\n";
    ++n;
  }
  std::cerr<<"evaluated "<<n<<" points\n";
}
