#pragma once

namespace go2_gateway {

class SportApi {
 public:
  virtual ~SportApi() = default;
  virtual int BalanceStand() = 0;
  virtual int Move(float vx, float vy, float vyaw) = 0;
  virtual int StopMove() = 0;
};

}  // namespace go2_gateway
