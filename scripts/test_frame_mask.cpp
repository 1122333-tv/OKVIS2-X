#include <okvis/Frame.hpp>
#include <okvis/cameras/PinholeCamera.hpp>
#include <okvis/cameras/EquidistantDistortion.hpp>
#include <iostream>
class MaskRejectingDetector : public cv::Feature2D {
 public:
  void detect(cv::InputArray, std::vector<cv::KeyPoint>& points,cv::InputArray mask=cv::noArray()) override {
    if(!mask.empty()) throw std::runtime_error("Bundled BRISK cannot receive mask");
    points={cv::KeyPoint(50,40,5),cv::KeyPoint(53,40,5)};
  }
};
int main() {
  auto c=std::make_shared<okvis::cameras::PinholeCamera<okvis::cameras::EquidistantDistortion>>(
      100,80,30,30,50,40,okvis::cameras::EquidistantDistortion(0,0,0,0));
  cv::Mat mask(80,100,CV_8UC1,cv::Scalar(255));mask.at<uchar>(40,50)=0;c->setMask(mask);
  okvis::Frame f;f.setImage(cv::Mat(80,100,CV_8UC1,cv::Scalar(0)));f.setGeometry(c);
  f.setDetector(std::make_shared<MaskRejectingDetector>());
  if(f.detect()!=1) return 1;
  Eigen::Vector2d p;f.getKeypoint(0,p);
  if((p-Eigen::Vector2d(53,40)).norm()>1e-9)return 2;
  std::cout<<"Detection without mask argument filters excluded centers before description\n";
}
