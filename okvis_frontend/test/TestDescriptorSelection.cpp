#include <okvis/DescriptorSelection.hpp>
#include <array>
#include <iostream>
#include <limits>
#include <stdexcept>

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

int main() {
  try {
    size_t count = 0, slot = 0;
    std::vector<double> scores(3, 1.0);
    // All references excluded, including an invalid acos-derived score: these
    // must not create a descriptor row backed by arbitrary previous pool data.
    for (double score : {1.0, 2.0, std::numeric_limits<double>::infinity(),
                         std::numeric_limits<double>::quiet_NaN()}) {
      require(!okvis::detail::selectDescriptorSlot(score, scores, count, slot),
              "ineligible descriptor selected");
      require(count == 0, "empty selection exposes an unwritten row");
    }
    std::array<double, 6> candidates{{0.8, 0.5, 0.7, 0.2, 0.9, 0.1}};
    std::array<size_t, 6> expectedSlots{{0, 1, 2, 0, 0, 2}};
    for (size_t i = 0; i < candidates.size(); ++i) {
      const bool selected = okvis::detail::selectDescriptorSlot(candidates[i], scores, count, slot);
      require(selected == (i != 4), "best-three retention changed");
      if (selected) require(slot == expectedSlots[i], "replacement slot changed");
      require(count == std::min(i + 1, size_t(3)), "occupied slot count is incorrect");
    }
    require(scores == std::vector<double>({0.2, 0.5, 0.1}), "incorrect retained scores");
    std::vector<double> empty;
    count = 0;
    require(!okvis::detail::selectDescriptorSlot(0.1, empty, count, slot), "zero-capacity selection");
    std::cout << "Descriptor selection regression passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
