#include "go2_gateway/pumped_sport_api.hpp"

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>

namespace go2_gateway {
namespace {

class PumpedSportApi final : public SportApi {
 public:
  PumpedSportApi(std::unique_ptr<SportApi> backend,
                 std::chrono::milliseconds move_period)
      : backend_(std::move(backend)), move_period_(move_period) {
    if (!backend_) {
      throw std::invalid_argument("pumped SportApi requires a backend");
    }
    if (move_period_ <= std::chrono::milliseconds::zero()) {
      throw std::invalid_argument("move period must be positive");
    }
    worker_ = std::thread([this] { worker_loop(); });
  }

  ~PumpedSportApi() override {
    {
      std::lock_guard<std::mutex> lock(state_mutex_);
      stopping_ = true;
      moving_ = false;
      ++generation_;
    }
    wake_.notify_all();
    if (worker_.joinable()) {
      worker_.join();
    }
    std::lock_guard<std::mutex> backend_lock(backend_mutex_);
    backend_->StopMove();
  }

  int BalanceStand() override {
    clear_motion_target();
    int result = 0;
    {
      std::lock_guard<std::mutex> backend_lock(backend_mutex_);
      result = backend_->BalanceStand();
    }
    if (result == 0) {
      std::lock_guard<std::mutex> lock(state_mutex_);
      prepared_ = true;
    }
    return result;
  }

  int Move(float vx, float vy, float vyaw) override {
    {
      std::lock_guard<std::mutex> lock(state_mutex_);
      vx_ = vx;
      vy_ = vy;
      vyaw_ = vyaw;
      moving_ = true;
      ++generation_;
    }
    wake_.notify_all();
    return 0;
  }

  int StopMove() override {
    clear_motion_target();
    std::lock_guard<std::mutex> backend_lock(backend_mutex_);
    return backend_->StopMove();
  }

  int PollError() override { return worker_error_.exchange(0); }

 private:
  void clear_motion_target() {
    {
      std::lock_guard<std::mutex> lock(state_mutex_);
      moving_ = false;
      ++generation_;
    }
    wake_.notify_all();
  }

  void worker_loop() {
    std::unique_lock<std::mutex> state_lock(state_mutex_);
    while (!stopping_) {
      wake_.wait(state_lock, [this] { return stopping_ || moving_; });
      if (stopping_) {
        break;
      }

      if (!prepared_) {
        state_lock.unlock();
        int prepare_result = 0;
        {
          std::lock_guard<std::mutex> backend_lock(backend_mutex_);
          prepare_result = backend_->BalanceStand();
        }
        state_lock.lock();
        if (prepare_result != 0) {
          worker_error_.store(prepare_result);
          moving_ = false;
          prepared_ = false;
          ++generation_;
          continue;
        }
        prepared_ = true;
        if (stopping_ || !moving_) {
          continue;
        }
      }

      const float vx = vx_;
      const float vy = vy_;
      const float vyaw = vyaw_;
      const std::uint64_t generation = generation_;
      state_lock.unlock();

      int result = 0;
      {
        std::lock_guard<std::mutex> backend_lock(backend_mutex_);
        result = backend_->Move(vx, vy, vyaw);
      }

      state_lock.lock();
      if (result != 0) {
        worker_error_.store(result);
        moving_ = false;
        prepared_ = false;
        ++generation_;
        continue;
      }

      wake_.wait_for(state_lock, move_period_, [this, generation] {
        return stopping_ || !moving_ || generation_ != generation;
      });
    }
  }

  std::unique_ptr<SportApi> backend_;
  const std::chrono::milliseconds move_period_;
  std::mutex state_mutex_;
  std::mutex backend_mutex_;
  std::condition_variable wake_;
  std::thread worker_;
  std::atomic<int> worker_error_{0};
  float vx_{0.0F};
  float vy_{0.0F};
  float vyaw_{0.0F};
  std::uint64_t generation_{0};
  bool moving_{false};
  bool prepared_{false};
  bool stopping_{false};
};

}  // namespace

std::unique_ptr<SportApi> make_pumped_sport_api(
    std::unique_ptr<SportApi> backend,
    std::chrono::milliseconds move_period) {
  return std::make_unique<PumpedSportApi>(std::move(backend), move_period);
}

}  // namespace go2_gateway
