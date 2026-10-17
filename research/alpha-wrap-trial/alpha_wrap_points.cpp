#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/alpha_wrap_3.h>
#include <CGAL/IO/polygon_mesh_io.h>
#include <fstream>
#include <iostream>
#include <vector>

using Kernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using Point = Kernel::Point_3;
using Mesh = CGAL::Surface_mesh<Point>;

int main(int argc, char** argv) {
  if (argc != 5) {
    std::cerr << "usage: alpha_wrap_points input.xyz alpha_mm offset_mm output.off\n";
    return 2;
  }
  std::ifstream file(argv[1]);
  if (!file) { std::cerr << "input open failed\n"; return 2; }
  std::vector<Point> points;
  double x,y,z;
  while (file >> x >> y >> z) points.emplace_back(x,y,z);
  const double alpha=std::stod(argv[2]);
  const double offset=std::stod(argv[3]);
  std::cerr << "points=" << points.size() << " alpha=" << alpha
            << " offset=" << offset << std::endl;
  Mesh result;
  CGAL::alpha_wrap_3(points,alpha,offset,result);
  std::cerr << "result vertices=" << result.number_of_vertices()
            << " faces=" << result.number_of_faces() << std::endl;
  if (!CGAL::IO::write_polygon_mesh(argv[4],result)) {
    std::cerr << "output write failed\n";return 3;
  }
  return 0;
}
