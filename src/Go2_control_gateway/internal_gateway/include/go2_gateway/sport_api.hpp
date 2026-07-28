#pragma once

#include <memory>
#include <string>

namespace go2_gateway {

class SportApi {
 public:
  virtual ~SportApi() = default;
  virtual int BalanceStand() = 0;
  virtual int Move(float vx, float vy, float vyaw) = 0;
  virtual int StopMove() = 0;
};

std::unique_ptr<SportApi> make_dry_run_sport_api();
std::unique_ptr<SportApi> make_unitree_sport_api(
    const std::string& interface_name);

}  // namespace go2_gateway
