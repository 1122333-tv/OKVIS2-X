#pragma once
#include <cstdint>

namespace okvis {
// Estimator IMU support on both sides of the corrected image timestamp.
// Readers and input validation must use this same requirement.
constexpr int64_t imuTemporalOverlapNs = 20000000;
constexpr double imuTemporalOverlap = imuTemporalOverlapNs * 1e-9;
}
