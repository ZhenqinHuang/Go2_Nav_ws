#include "go2_gateway/sport_api.hpp"

#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/go2/sport/sport_client.hpp>

#include <memory>
#include <string>

namespace go2_gateway {

class UnitreeSportApi final : public SportApi {
 public:
  explicit UnitreeSportApi(const std::string& interface_name) {
    unitree::robot::ChannelFactory::Instance()->Init(0, interface_name);
    client_ = std::make_unique<unitree::robot::SportClient>();
    client_->SetTimeout(3.0F);
    client_->Init();
  }

  int BalanceStand() override { return client_->BalanceStand(); }

  int Move(float vx, float vy, float vyaw) override {
    return client_->Move(vx, vy, vyaw);
  }

  int StopMove() override { return client_->StopMove(); }

 private:
  std::unique_ptr<unitree::robot::SportClient> client_;
};

std::unique_ptr<SportApi> make_unitree_sport_api(
    const std::string& interface_name) {
  return std::make_unique<UnitreeSportApi>(interface_name);
}

}  // namespace go2_gateway
