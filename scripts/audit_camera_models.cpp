// OKVIS versus the local equidistant theta polynomial; no fitted parameters.
#include <iostream>
#include <iomanip>
#include <opencv2/imgcodecs.hpp>
#include <okvis/cameras/PinholeCamera.hpp>
#include <okvis/cameras/EquidistantDistortion.hpp>

int main(int argc, char** argv) {
  if(argc != 3) return 2;
  cv::FileStorage fs(argv[1], cv::FileStorage::READ);
  std::cout << std::setprecision(17) << "[";
  int ci=0;
  for (auto n : fs["cameras"]) {
    Eigen::Matrix<double,8,1> p;
    p << double(n["focal_length"][0]),double(n["focal_length"][1]),
         double(n["principal_point"][0]),double(n["principal_point"][1]),
         double(n["distortion_coefficients"][0]),double(n["distortion_coefficients"][1]),
         double(n["distortion_coefficients"][2]),double(n["distortion_coefficients"][3]);
    okvis::cameras::PinholeCamera<okvis::cameras::EquidistantDistortion> o(
      static_cast<int>(n["image_dimension"][0]),static_cast<int>(n["image_dimension"][1]),p[0],p[1],p[2],p[3],
      okvis::cameras::EquidistantDistortion(p[4],p[5],p[6],p[7]));
    cv::Mat mask=cv::imread(std::string(argv[2])+"/cam"+std::to_string(ci)+".png",0);
    if(mask.empty()) return 3;
    double maxround=0,maxproj=0,maxrefined=0,minz=1,minderivative=1; long count=0,failed=0;
    for(int y=0;y<mask.rows;++y) for(int x=0;x<mask.cols;++x) {
      if(mask.at<uchar>(y,x)>127) continue;
      Eigen::Vector2d uv(x,y); Eigen::Vector3d ro;
      bool vo=o.backProject(uv,&ro);
      Eigen::Vector2d round;
      auto status=o.project(ro,&round);
      if(!vo || !ro.allFinite() || !round.allFinite() || (status!=okvis::cameras::ProjectionStatus::Successful && status!=okvis::cameras::ProjectionStatus::OutsideImage) || ro.z()<=0 || (round-uv).norm()>1e-5) {++failed;continue;}
      double radius=std::hypot((x-p[2])/p[0],(y-p[3])/p[1]);
      double theta=radius;
      for(int j=0;j<30;++j) {
        double f=theta-radius,df=1;
        for(int k=1;k<=4;++k) {f+=p[k+3]*std::pow(theta,2*k+1);df+=(2*k+1)*p[k+3]*std::pow(theta,2*k);}
        theta-=f/df;
      }
      double derivative=1;
      for(int k=1;k<=4;++k) derivative+=(2*k+1)*p[k+3]*std::pow(theta,2*k);
      minderivative=std::min(minderivative,derivative);minz=std::min(minz,std::cos(theta));
      Eigen::Vector3d refined(0,0,1);
      if(radius>1e-12) refined=Eigen::Vector3d((x-p[2])/p[0]*std::sin(theta)/radius,(y-p[3])/p[1]*std::sin(theta)/radius,std::cos(theta));
      maxrefined=std::max(maxrefined,std::atan2(refined.cross(ro).norm(),refined.dot(ro)));
      double f=theta-radius;
      for(int k=1;k<=4;++k) f+=p[k+3]*std::pow(theta,2*k+1);
      if(!std::isfinite(theta) || theta<0 || theta>=std::acos(-1.)/2 || !std::isfinite(derivative) || std::abs(f)>1e-10) {++failed;continue;}
      Eigen::Vector2d projected;
      o.project(refined,&projected);
      if(!projected.allFinite()) {++failed;continue;}
      maxround=std::max(maxround,(round-uv).norm());
      maxproj=std::max(maxproj,(projected-uv).norm()); ++count;

    }
    if(ci) std::cout << ",";
    std::cout << "{\"camera\":"<<ci<<",\"pixels\":"<<count<<",\"failed\":"<<failed
      <<",\"max_roundtrip_px\":"<<maxround
      <<",\"max_refined_bearing_angle_rad\":"<<maxrefined<<",\"min_refined_z\":"<<minz<<",\"min_radial_derivative\":"<<minderivative
      <<",\"max_projection_difference_px\":"<<maxproj<<",\"boundary_probes_without_mask\":[";
    bool firstProbe=true;
    for(double degrees : {85.,89.999,90.,90.001,100.,110.}) {
      double theta=degrees*std::acos(-1.)/180.;
      Eigen::Vector3d ray(std::sin(theta),0,std::cos(theta));
      Eigen::Vector2d uv;auto status=o.project(ray,&uv);
      if(!firstProbe) std::cout<<",";
      std::cout<<"{\"angle_deg\":"<<degrees<<",\"okvis_status\":"<<int(status)<<"}";
      firstProbe=false;
    }
    std::cout<<"]}";
    ++ci;
  }
  std::cout << "]\n";
}
