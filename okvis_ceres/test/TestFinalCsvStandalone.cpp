// SPDX-License-Identifier: BSD-3-Clause
#include <okvis/ViSlamBackend.hpp>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <new>
#include <sstream>
#include <stdexcept>
#include <unistd.h>

class StateProbe : public okvis::ViGraph {
 public:
  static void checkDefault() {
    alignas(State) unsigned char storage[sizeof(State)];
    std::memset(storage, 0xa5, sizeof(storage));
    State* state = new(storage) State;
    const auto mode = state->gpsMode;
    state->~State();
    if (mode != okvis::gpsStatus::Off)
      throw std::runtime_error("Pure VIO state has undefined GPS mode");
  }
};
std::vector<std::string> split(const std::string& line) {
  std::stringstream stream(line); std::string cell; std::vector<std::string> cells;
  while (std::getline(stream, cell, ',')) cells.push_back(cell);
  return cells;
}
int main() {
  StateProbe::checkDefault();
  okvis::ImuParameters imu{};
  imu.use=true; imu.T_BS.setIdentity(); imu.a_max=160; imu.g_max=10; imu.g=9.81;
  imu.sigma_g_c=.001; imu.sigma_a_c=.01; imu.sigma_bg=.01; imu.sigma_ba=.1;
  imu.sigma_gw_c=.0001; imu.sigma_aw_c=.001;
  imu.a0.setZero(); imu.g0.setZero(); imu.s_a.setOnes();
  okvis::ImuMeasurementDeque samples;
  for (int i=0;i<=300;++i) {
    okvis::ImuMeasurement sample;
    sample.timeStamp=okvis::Time(.95+i*.001);
    sample.measurement.accelerometers=Eigen::Vector3d(.1,0,9.81);
    sample.measurement.gyroscopes=Eigen::Vector3d::Zero(); samples.push_back(sample);
  }
  okvis::ViSlamBackend backend; backend.addImu(imu);
  okvis::cameras::NCameraSystem cameras;
  for (double time : {1.0,1.1})
    backend.addStates(std::make_shared<okvis::MultiFrame>(cameras,okvis::Time(time)),samples,true);
  char path[]="/tmp/okvis-final-csv-XXXXXX";
  int fd=mkstemp(path); if (fd<0) throw std::runtime_error("mkstemp failed"); close(fd);
  if (!backend.writeFinalCsvTrajectory(path)) throw std::runtime_error("Export failed");
  std::ifstream stream(path);std::string line;
  std::getline(stream,line);const auto header=split(line);
  if (header.size()!=21 || header.back()!=" keyframeId")
    throw std::runtime_error("Final CSV header is missing metadata columns");
  int rows=0;
  while (std::getline(stream,line)) {
    const auto cells=split(line);++rows;
    if (cells.size()!=header.size() || std::stoul(cells[17])!=0 || std::stoul(cells[19])!=0)
      throw std::runtime_error("Undefined pure VIO GPS metadata or inconsistent CSV width");
    if (std::stoul(cells[18])!=unsigned(rows)) throw std::runtime_error("Wrong state ID");
  }
  stream.close();std::remove(path);
  if (rows!=2) throw std::runtime_error("Missing exported states");
  std::cout << "Final CSV: 21 columns, initialized GPS metadata, 2 complete states\n";
}
