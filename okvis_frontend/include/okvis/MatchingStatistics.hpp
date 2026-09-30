#pragma once

#include <cstddef>
#include <vector>

namespace okvis {
namespace detail {
// Sum/count aggregation makes the result independent of partition population.
// Empty input supplies no evidence of a large error; tracking-loss handling is
// based on correspondence count, not on this mean.
struct MatchingStatistics {
  double sum = 0.0;
  std::size_t count = 0;
  void add(double errorSum, std::size_t matches) {
    sum += errorSum;
    count += matches;
  }
  double mean() const { return count ? sum / double(count) : 0.0; }
};
// Track the winning candidate per keypoint, not the number of improvements.
class FinalMatchStatistics {
 public:
  explicit FinalMatchStatistics(std::size_t size) : errors_(size, 0.0), matched_(size, false) {}
  void select(std::size_t keypoint, double error) {
    errors_.at(keypoint) = error;
    matched_.at(keypoint) = true;
  }
  MatchingStatistics summary() const {
    MatchingStatistics result;
    for (std::size_t k = 0; k < errors_.size(); ++k) {
      if (matched_[k]) result.add(errors_[k], 1);
    }
    return result;
  }
 private:
  std::vector<double> errors_;
  std::vector<bool> matched_;
};
}  // namespace detail
}  // namespace okvis
