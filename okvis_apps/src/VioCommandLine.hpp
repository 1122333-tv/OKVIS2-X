#pragma once

#include <stdexcept>
#include <string>
#include <vector>

namespace okvis {
struct VioCommandLine {
  std::string config, dataset, output;
  bool rpg = false;
  bool deterministic = false;
};

// Keep the historical positional interface; optional switches may follow it.
inline VioCommandLine parseVioCommandLine(int argc, char** argv) {
  VioCommandLine options;
  std::vector<std::string> positional;
  bool seen = false;
  for (int i = 1; i < argc; ++i) {
    const std::string arg(argv[i]);
    if (arg == "--deterministic") {
      if (seen) throw std::invalid_argument("Duplicate --deterministic");
      seen = true;
      options.deterministic = true;
      if (i + 1 < argc) {
        const std::string next(argv[i + 1]);
        if (next == "0" || next == "1") {
          options.deterministic = next == "1";
          ++i;
        } else if (next.empty() || next[0] != '-') {
          throw std::invalid_argument("--deterministic accepts only 0 or 1; put positional arguments first");
        }
      }
    } else if (arg == "-rpg") {
      options.rpg = true;
    } else if (!arg.empty() && arg[0] == '-') {
      throw std::invalid_argument("Unknown option: " + arg);
    } else {
      positional.push_back(arg);
    }
  }
  if (positional.size() < 2 || positional.size() > 3)
    throw std::invalid_argument("Expected configuration, dataset, and optional output directory");
  options.config = positional[0];
  options.dataset = positional[1];
  options.output = positional.size() == 3 ? positional[2] : positional[1];
  return options;
}
}  // namespace okvis
