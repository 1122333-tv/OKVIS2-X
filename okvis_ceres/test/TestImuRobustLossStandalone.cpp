// SPDX-License-Identifier: BSD-3-Clause
#include <okvis/ViGraphEstimator.hpp>
#include <cmath>
#include <iostream>
#include <stdexcept>

double factorCost(double scale, bool clone, bool merged=false) {
  okvis::ImuParameters imu{};
  imu.use=true;
  imu.T_BS.setIdentity();
  imu.a_max=160; imu.g_max=10; imu.g=9.81;
  imu.sigma_g_c=.001; imu.sigma_a_c=.01;
  imu.sigma_bg=.01; imu.sigma_ba=.1;
  imu.sigma_gw_c=.0001; imu.sigma_aw_c=.001;
  imu.a0.setZero(); imu.g0.setZero(); imu.s_a.setOnes();
  imu.huber_loss_scale=scale;
  okvis::ImuMeasurementDeque samples;
  for (int i=0;i<=300;++i) {
    okvis::ImuMeasurement sample;
    sample.timeStamp=okvis::Time(.95+i*.001);
    sample.measurement.accelerometers=Eigen::Vector3d(.1,0,9.81);
    sample.measurement.gyroscopes=Eigen::Vector3d(0,0,1);
    samples.push_back(sample);
  }
  okvis::ViGraphEstimator graph;
  graph.addImu(imu);
  okvis::cameras::NCameraSystem cameras;
  const auto first=graph.addStatesInitialise(okvis::Time(1.0),samples,cameras);
  const auto middle=graph.addStatesPropagate(okvis::Time(1.1),samples,!merged);
  const auto next=merged ? graph.addStatesPropagate(okvis::Time(1.2),samples,true) : middle;
  // Force a known visual/IMU disagreement; do not optimize it away.
  graph.setPose(next,graph.pose(first));
  graph.setSpeedAndBias(next,graph.speedAndBias(first));
  if (merged) graph.eliminateStateByImuMerge(middle,first);
  if (clone) {
    okvis::ViGraph copied;
    copied.addImu(imu);
    copied.addStatesFromOther(first,graph);
    copied.addStatesFromOther(next,graph);
    copied.optimise(0,1,false);
    return copied.summary().initial_cost;
  }
  graph.optimise(0,1,false);
  return graph.summary().initial_cost;
}

int main() {
  if (okvis::ImuParameters{}.huber_loss_scale!=0.0)
    throw std::runtime_error("Legacy default changed");
  const double quadratic=factorCost(0,false), robust=factorCost(5,false);
  const double mergedQuadratic=factorCost(0,false,true);
  const double mergedRobust=factorCost(5,false,true);
  const double expectedMerged=5.0*std::sqrt(2.0*mergedQuadratic)-12.5;
  if (std::abs(mergedRobust-expectedMerged)>1e-8*expectedMerged)
    throw std::runtime_error("Merging IMU states discarded the robust loss policy");
  if (std::abs(factorCost(5,true,true)-mergedRobust)>1e-8*mergedRobust)
    throw std::runtime_error("Merged-factor cloning changed loss policy");
  const double copied=factorCost(5,true), copiedQuadratic=factorCost(0,true);
  const double largeScale=factorCost(1000,false);
  const double expectedHuber=5.0*std::sqrt(2.0*quadratic)-12.5;
  if (std::abs(largeScale-quadratic)>1e-8*quadratic
      || std::abs(robust-expectedHuber)>1e-8*robust)
    throw std::runtime_error("Huber inlier/outlier cost does not match whitened residual norm");
  if (!(std::isfinite(quadratic) && quadratic>0 && robust>0 && robust<quadratic*.5))
    throw std::runtime_error("Huber loss not attached to propagated IMU factor");
  if (std::abs(copied-robust)>1e-8*robust || std::abs(copiedQuadratic-quadratic)>1e-8*quadratic)
    throw std::runtime_error("Cloning changed IMU loss policy");
  std::cout << "quadratic=" << quadratic << " huber=" << robust << " cloned_huber=" << copied << " merged_quadratic=" << mergedQuadratic << " merged_huber=" << mergedRobust << '\n';
}
