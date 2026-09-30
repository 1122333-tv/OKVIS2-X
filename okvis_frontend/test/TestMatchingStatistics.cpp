#include <okvis/MatchingStatistics.hpp>
#include <cmath>
#include <iostream>
int main() {
  okvis::detail::MatchingStatistics empty;
  if (empty.mean()!=0.0 || !std::isfinite(empty.mean())) return 1;
  okvis::detail::MatchingStatistics uneven;
  uneven.add(12,3); uneven.add(20,1); uneven.add(0,0);
  if (uneven.count!=4 || uneven.mean()!=8) return 2;
  okvis::detail::MatchingStatistics combined;
  combined.add(32,4);
  if (combined.mean()!=uneven.mean()) return 3;
  okvis::detail::FinalMatchStatistics selected(4);
  selected.select(1,12); selected.select(1,5); selected.select(1,2);
  selected.select(3,8);
  const auto stats=selected.summary();
  if (stats.count!=2 || stats.sum!=10 || stats.mean()!=5) return 4;
  okvis::detail::FinalMatchStatistics none(0);
  if (none.summary().count || none.summary().mean()!=0) return 5;
  std::cout << "MatchingStatistics passed\n";
}
