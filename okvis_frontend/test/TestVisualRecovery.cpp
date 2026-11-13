#include <okvis/VisualRecovery.hpp>
#include <limits>
#include <iostream>
int main() {
  using okvis::detail::useVisualRecovery;
  okvis::detail::RecoveryEvidence e;
  e.correspondences=100;e.inliers=80;e.cameras=4;e.accepted=true;
  if (!useVisualRecovery(true,true,true,false,12,5,e)) return 1;
  if (useVisualRecovery(false,true,true,false,12,5,e)) return 2;
  if (useVisualRecovery(true,false,true,false,12,5,e)) return 3;
  if (useVisualRecovery(true,true,false,false,12,5,e)) return 4;
  if (useVisualRecovery(true,true,true,true,12,5,e)) return 5;
  if (useVisualRecovery(true,true,true,false,5,5,e)) return 6;
  if (useVisualRecovery(true,true,true,false,std::numeric_limits<double>::quiet_NaN(),5,e)) return 7;
  e.cameras=1;if (useVisualRecovery(true,true,true,false,12,5,e)) return 8;
  e.cameras=4;e.inliers=70;if (useVisualRecovery(true,true,true,false,12,5,e)) return 9;
  e.inliers=80;e.accepted=false;if (useVisualRecovery(true,true,true,false,12,5,e)) return 10;
  e.accepted=true;e.inliers=9;e.correspondences=9;if (useVisualRecovery(true,true,true,false,12,5,e)) return 11;
  e.inliers=101;e.correspondences=100;if (useVisualRecovery(true,true,true,false,12,5,e)) return 12;
  std::cout << "VisualRecovery rejection gates passed\n";
}
