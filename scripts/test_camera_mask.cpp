#include <okvis/cameras/PinholeCamera.hpp>
#include <okvis/cameras/EquidistantDistortion.hpp>
#include <iostream>
int main() {
  okvis::cameras::PinholeCamera<okvis::cameras::EquidistantDistortion> c(
    100,80,30,30,50,40,okvis::cameras::EquidistantDistortion(0,0,0,0));
  cv::Mat m(80,100,CV_8UC1,cv::Scalar(255));m.at<uchar>(40,50)=0;
  if(!c.setMask(m))return 1;
  Eigen::Vector2d uv;
  if(c.project(Eigen::Vector3d(0,0,1),&uv)!=okvis::cameras::ProjectionStatus::Masked)return 2;
  if(c.project(Eigen::Vector3d(.1,0,1),&uv)!=okvis::cameras::ProjectionStatus::Successful)return 3;
  if(c.project(Eigen::Vector3d(0,0,-1),&uv)==okvis::cameras::ProjectionStatus::Successful)return 4;
  if(c.project(Eigen::Vector3d(std::numeric_limits<double>::quiet_NaN(),0,1),&uv)==okvis::cameras::ProjectionStatus::Successful)return 5;
  std::cout<<"OpenCV mask semantics and rear-hemisphere rejection passed\n";
}
