#include "go2_gateway/sport_api.hpp"
#include "go2_gateway/pumped_sport_api.hpp"

#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/go2/sport/sport_client.hpp>

#include <chrono>
#include <memory>
#include <string>

namespace go2_gateway {

class SyncUnitreeSportApi final : public SportApi {
 public:
  explicit SyncUnitreeSportApi(const std::string& interface_name) {
    unitree::robot::ChannelFactory::Instance()->Init(0, interface_name);
    client_ = std::make_unique<unitree::robot::SportClient>();
    client_->SetTimeout(3.0F);
    client_->Init();
  }

  int BalanceStand() override { return client_->BalanceStand(); }
  int StandDown() override { return client_->StandDown(); }

  int Move(float vx, float vy, float vyaw) override {
    return client_->Move(vx, vy, vyaw);
  }

  int StopMove() override { return client_->StopMove(); }

 private:
  std::unique_ptr<unitree::robot::SportClient> client_;
};

std::unique_ptr<SportApi> make_unitree_sport_api(
    const std::string& interface_name) {
  return make_pumped_sport_api(
      std::make_unique<SyncUnitreeSportApi>(interface_name),
      std::chrono::milliseconds(100));
}

}  // namespace go2_gateway
