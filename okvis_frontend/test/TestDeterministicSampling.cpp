#include <okvis/ViSlamBackend.hpp>
#include <okvis/MultiFrame.hpp>
#include <okvis/cameras/PinholeCamera.hpp>
#include <okvis/cameras/EquidistantDistortion.hpp>
#include <opengv/absolute_pose/FrameNoncentralAbsoluteAdapter.hpp>
#include <opengv/absolute_pose/LoopclosureNoncentralAbsoluteAdapter.hpp>
#include <opengv/relative_pose/FrameRelativeAdapter.hpp>
#include <opengv/sac_problems/absolute_pose/FrameAbsolutePoseSacProblem.hpp>
#include <opengv/sac_problems/relative_pose/FrameRelativePoseSacProblem.hpp>
#include <opengv/sac_problems/relative_pose/FrameRotationOnlySacProblem.hpp>
#include <algorithm>
#include <iostream>
#include <numeric>
#include <stdexcept>

void require(bool ok, const char* message) {
  if (!ok) throw std::runtime_error(message);
}
template<class Problem> struct Inspect : Problem {
  using Problem::Problem;
  bool fixed() const { return this->rng_alg_ == std::mt19937(12345u); }
};
template<class Problem> void compare(Problem& a, Problem& b) {
  require(a.fixed() && b.fixed(), "fixed seed was not forwarded");
  // Sampling only: no geometry is evaluated. Synthetic candidate IDs exercise
  // the real OpenGV index shuffle without needing a fitted trajectory.
  std::vector<int> indices(40);
  std::iota(indices.begin(), indices.end(), 10);
  if (a.getIndices()->empty()) { a.setIndices(indices); b.setIndices(indices); }
  const auto candidates = *a.getIndices();
  std::vector<int> first;
  bool varied = false;
  for (int i = 0; i < 100; ++i) {
    std::vector<int> x(5), y(5);
    a.drawIndexSample(x); b.drawIndexSample(y);
    require(x == y, "independent instances produced different samples");
    for (int id : x) require(std::find(candidates.begin(), candidates.end(), id) != candidates.end(),
                            "sample outside supplied candidates");
    if (i == 0) first = x;
    else varied |= x != first;
  }
  require(varied, "generator was reset between draws");
}
int main() {
  try {
    okvis::cameras::NCameraSystem cameras;
    cameras.addCamera(std::make_shared<okvis::kinematics::Transformation>(),
      std::shared_ptr<const okvis::cameras::CameraBase>(
        okvis::cameras::PinholeCamera<okvis::cameras::EquidistantDistortion>::createTestObject()),
      okvis::cameras::NCameraSystem::Equidistant);
    auto frame = std::make_shared<okvis::MultiFrame>();
    frame->resetCameraSystemAndFrames(cameras);
    frame->setTimestamp(okvis::Time(1, 0));
    okvis::ViSlamBackend backend;
    okvis::CameraParameters camera{};
    backend.addCamera(camera);
    okvis::ImuParameters imu{};
    imu.use = false; imu.g0.setZero(); imu.a0.setZero();
    imu.s_a.setOnes(); imu.g = 9.81;
    imu.sigma_bg = .01; imu.sigma_ba = .1;
    backend.addImu(imu);
    require(backend.addStates(frame, {}, true), "fixture initialization failed");
    opengv::absolute_pose::FrameNoncentralAbsoluteAdapter absolute(backend, cameras, frame);
    opengv::relative_pose::FrameRelativeAdapter relative(backend, cameras, frame->id(), 0, frame->id(), 0);
    using A = Inspect<opengv::sac_problems::absolute_pose::FrameAbsolutePoseSacProblem<opengv::absolute_pose::FrameNoncentralAbsoluteAdapter>>;
    using R = Inspect<opengv::sac_problems::relative_pose::FrameRelativePoseSacProblem>;
    using O = Inspect<opengv::sac_problems::relative_pose::FrameRotationOnlySacProblem>;
    const std::vector<int> indices{1,3,5,7,9,11,13,15};
    A a(absolute,A::GP3P,false), b(absolute,A::GP3P,false);
    A ai(absolute,A::GP3P,indices,false), bi(absolute,A::GP3P,indices,false);
    R r(relative,R::STEWENIUS,false), s(relative,R::STEWENIUS,false);
    R ri(relative,R::STEWENIUS,indices,false), si(relative,R::STEWENIUS,indices,false);
    O o(relative,false), p(relative,false), oi(relative,indices,false), pi(relative,indices,false);
    require(*ai.getIndices() == indices && *ri.getIndices() == indices && *oi.getIndices() == indices,
            "indexed overload lost candidate indices");
    compare(a,b); compare(ai,bi); compare(r,s); compare(ri,si); compare(o,p); compare(oi,pi);
    A ad(absolute,A::GP3P), adi(absolute,A::GP3P,indices);
    R rd(relative,R::STEWENIUS), rdi(relative,R::STEWENIUS,indices);
    O od(relative), odi(relative,indices);
    require(!ad.fixed() && !adi.fixed() && !rd.fixed() && !rdi.fixed() && !od.fixed() && !odi.fixed(),
            "default construction changed to fixed sampling");
    require(!okvis::FrontendParameters{}.deterministic, "frontend default changed");
    std::cout << "PASS: three wrappers, indexed overloads, 100 draws each, default seeds\n";
    return 0;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
