#pragma once
#include <cmath>
#include <cstddef>
namespace okvis {
namespace detail {
struct RecoveryEvidence {
  std::size_t correspondences = 0;
  std::size_t inliers = 0;
  std::size_t cameras = 0;
  bool accepted = false;
};
inline bool useVisualRecovery(bool enabled, bool initialized, bool imu,
                              bool loopClosure, double predictionError,
                              double threshold, const RecoveryEvidence& e) {
  return enabled && initialized && imu && !loopClosure
      && std::isfinite(predictionError) && predictionError > threshold
      && e.accepted && e.inliers >= 20 && e.cameras >= 2
      && e.correspondences >= e.inliers
      && double(e.inliers) > .7 * double(e.correspondences);
}
}  // namespace detail
}  // namespace okvis
