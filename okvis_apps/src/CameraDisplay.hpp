#pragma once

#include <algorithm>
#include <map>
#include <string>
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>

// Copy native-resolution visualisations without resampling. HighGUI scales only
// the window presentation; enlarging it retains the original feature detail.
inline cv::Mat cameraDisplayGrid(const std::map<std::string, cv::Mat>& images,
                                size_t cameraCount) {
  if (images.empty() || cameraCount == 0) return {};
  int width = 0, imageHeight = 0;
  for (size_t i = 0; i < cameraCount; ++i) {
    auto image = images.find("cam" + std::to_string(i));
    if (image == images.end()) image = images.find("rgb" + std::to_string(i));
    if (image != images.end() && !image->second.empty()) {
      width = std::max(width, image->second.cols);
      imageHeight = std::max(imageHeight, image->second.rows);
    }
  }
  if (width == 0 || imageHeight == 0) return {};
  constexpr int labelHeight = 32;
  const int height = imageHeight + labelHeight;
  const int columns = cameraCount == 1 ? 1 : 2;
  const int rows = (static_cast<int>(cameraCount) + columns - 1) / columns;
  cv::Mat grid(rows * height, columns * width, CV_8UC3, cv::Scalar::all(0));
  for (size_t i = 0; i < cameraCount; ++i) {
    std::string name = "cam" + std::to_string(i);
    auto image = images.find(name);
    if (image == images.end()) {
      name = "rgb" + std::to_string(i);
      image = images.find(name);
    }
    cv::Mat tile = grid(cv::Rect((i % columns) * width, (i / columns) * height,
                                width, height));
    if (image != images.end() && !image->second.empty()) {
      const cv::Mat& source = image->second;
      source.copyTo(tile(cv::Rect((width-source.cols)/2, (imageHeight-source.rows)/2,
                                 source.cols, source.rows)));
    } else {
      name = "cam" + std::to_string(i) + " (no image)";
    }
    cv::putText(tile, name, cv::Point(8, height-7), cv::FONT_HERSHEY_SIMPLEX,
                0.7, cv::Scalar::all(255), 1, cv::LINE_AA);
  }
  return grid;
}
