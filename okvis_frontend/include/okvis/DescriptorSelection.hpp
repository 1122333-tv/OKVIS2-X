#pragma once

#include <algorithm>
#include <cstddef>
#include <vector>

namespace okvis {
namespace detail {

// Retain the best bounded set of reference descriptors. Count occupied slots,
// not the largest slot index: zero eligible references must remain empty.
inline bool selectDescriptorSlot(double score, std::vector<double>& bestScores,
                                 size_t& selectedCount, size_t& slot) {
  double worstScore = 0.0;
  slot = 0;
  for (size_t i = 0; i < bestScores.size(); ++i) {
    if (bestScores[i] > worstScore) {
      worstScore = bestScores[i];
      slot = i;
    }
  }
  if (bestScores.empty() || !(score < bestScores[slot])) return false;
  bestScores[slot] = score;
  selectedCount = std::max(selectedCount, slot + 1);
  return true;
}

}  // namespace detail
}  // namespace okvis
