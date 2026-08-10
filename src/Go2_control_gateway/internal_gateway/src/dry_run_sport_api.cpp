#include "go2_gateway/sport_api.hpp"

#include <memory>

namespace go2_gateway {

class DryRunSportApi final : public SportApi {
 public:
  int BalanceStand() override { return 0; }

  int Move(float vx, float vy, float vyaw) override {
    vx_ = vx;
    vy_ = vy;
    vyaw_ = vyaw;
    return 0;
  }

  int StopMove() override {
    vx_ = 0.0F;
    vy_ = 0.0F;
    vyaw_ = 0.0F;
    return 0;
  }

 private:
  float vx_{0.0F};
  float vy_{0.0F};
  float vyaw_{0.0F};
};

std::unique_ptr<SportApi> make_dry_run_sport_api() {
  return std::make_unique<DryRunSportApi>();
}

}  // namespace go2_gateway
