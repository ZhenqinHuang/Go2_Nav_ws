#include <cstdlib>
#include <iostream>

#include "common/sport_request.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
  }
}

}  // namespace

int main() {
  unitree_api::msg::Request first;
  unitree_api::msg::Request second;

  go2_nav2::prepare_sport_request(first, 1006);
  go2_nav2::prepare_sport_request(second, 1008);

  require(first.header.identity.id != 0, "request identity is non-zero");
  require(second.header.identity.id != first.header.identity.id,
          "request identities are unique");
  require(first.header.identity.api_id == 1006, "RecoveryStand API id is set");
  require(second.header.identity.api_id == 1008, "Move API id is set");
  require(first.header.lease.id == 0, "lease id is zero");
  require(first.header.policy.priority == 0, "priority is zero");
  require(first.header.policy.noreply, "fire-and-forget policy is enabled");

  std::cout << "sport_request_test: PASS\n";
  return 0;
}
