#include "go2_gateway/pumped_sport_api.hpp"

#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <mutex>
#include <thread>
#include <tuple>
#include <vector>

namespace {

using namespace std::chrono_literals;

void require(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
  }
}

class RecordingSportApi final : public go2_gateway::SportApi {
 public:
  int BalanceStand() override {
    std::unique_lock<std::mutex> lock(mutex_);
    ++balance_calls_;
    balance_entered_.notify_all();
    balance_blocked_.wait(lock, [this] { return !block_balance_; });
    return 0;
  }

  int Move(float vx, float vy, float vyaw) override {
    std::unique_lock<std::mutex> lock(mutex_);
    moves_.emplace_back(vx, vy, vyaw);
    entered_.notify_all();
    blocked_.wait(lock, [this] { return !block_moves_; });
    return move_result_;
  }

  int StopMove() override {
    std::lock_guard<std::mutex> lock(mutex_);
    ++stop_calls_;
    return 0;
  }

  void block_moves() {
    std::lock_guard<std::mutex> lock(mutex_);
    block_moves_ = true;
  }

  void block_balance() {
    std::lock_guard<std::mutex> lock(mutex_);
    block_balance_ = true;
  }

  void release_balance() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      block_balance_ = false;
    }
    balance_blocked_.notify_all();
  }

  void release_moves() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      block_moves_ = false;
    }
    blocked_.notify_all();
  }

  void set_move_result(int result) {
    std::lock_guard<std::mutex> lock(mutex_);
    move_result_ = result;
  }

  bool wait_for_move_count(std::size_t count,
                           std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(mutex_);
    return entered_.wait_for(lock, timeout,
                             [this, count] { return moves_.size() >= count; });
  }

  bool wait_for_balance_count(int count,
                              std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(mutex_);
    return balance_entered_.wait_for(
        lock, timeout, [this, count] { return balance_calls_ >= count; });
  }

  int balance_calls() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return balance_calls_;
  }

  std::size_t move_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return moves_.size();
  }

  std::tuple<float, float, float> move_at(std::size_t index) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return moves_.at(index);
  }

  int stop_calls() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return stop_calls_;
  }

 private:
  mutable std::mutex mutex_;
  std::condition_variable entered_;
  std::condition_variable blocked_;
  std::condition_variable balance_entered_;
  std::condition_variable balance_blocked_;
  std::vector<std::tuple<float, float, float>> moves_;
  int balance_calls_{0};
  int stop_calls_{0};
  int move_result_{0};
  bool block_moves_{false};
  bool block_balance_{false};
};

void test_first_move_prepares_asynchronously_once() {
  auto backend = std::make_unique<RecordingSportApi>();
  auto* observed = backend.get();
  observed->block_balance();
  auto api = go2_gateway::make_pumped_sport_api(std::move(backend), 20ms);

  const auto started = std::chrono::steady_clock::now();
  require(api->Move(0.1F, 0.0F, 0.0F) == 0, "first Move is accepted");
  const auto elapsed = std::chrono::steady_clock::now() - started;
  require(elapsed < 50ms,
          "first Move does not wait for BalanceStand RPC");
  require(observed->wait_for_balance_count(1, 250ms),
          "worker performs BalanceStand before first Move");
  require(observed->move_count() == 0,
          "backend Move waits until BalanceStand succeeds");

  require(api->Move(0.2F, 0.0F, 0.0F) == 0,
          "latest velocity can replace target during preparation");
  observed->release_balance();
  require(observed->wait_for_move_count(1, 250ms),
          "worker sends Move after preparation");
  const auto [vx, vy, vyaw] = observed->move_at(0);
  require(std::fabs(vx - 0.2F) < 1e-6F && std::fabs(vy) < 1e-6F &&
              std::fabs(vyaw) < 1e-6F,
          "first backend Move uses latest velocity");

  require(api->StopMove() == 0, "StopMove succeeds");
  const auto previous_moves = observed->move_count();
  require(api->Move(0.3F, 0.0F, 0.0F) == 0,
          "Move after stop is accepted");
  require(observed->wait_for_move_count(previous_moves + 1, 250ms),
          "Move after stop reaches backend");
  require(observed->balance_calls() == 1,
          "BalanceStand runs only once per gateway process");
  require(api->StopMove() == 0, "final StopMove succeeds");
}

void test_move_returns_while_backend_is_blocked() {
  auto backend = std::make_unique<RecordingSportApi>();
  auto* observed = backend.get();
  observed->block_moves();
  auto api = go2_gateway::make_pumped_sport_api(std::move(backend), 20ms);

  const auto started = std::chrono::steady_clock::now();
  require(api->Move(0.2F, 0.0F, 0.0F) == 0, "Move is accepted");
  const auto elapsed = std::chrono::steady_clock::now() - started;
  require(elapsed < 50ms, "Move returns without waiting for backend RPC");
  require(observed->wait_for_move_count(1, 250ms),
          "worker enters backend Move");

  observed->release_moves();
  require(api->StopMove() == 0, "StopMove succeeds after worker release");
}

void test_worker_repeats_and_stop_halts_refresh() {
  auto backend = std::make_unique<RecordingSportApi>();
  auto* observed = backend.get();
  auto api = go2_gateway::make_pumped_sport_api(std::move(backend), 20ms);

  require(api->Move(0.2F, 0.0F, 0.0F) == 0, "Move is accepted");
  require(observed->wait_for_move_count(3, 300ms),
          "worker repeats latest Move");
  require(api->StopMove() == 0, "StopMove succeeds");
  const auto count_after_stop = observed->move_count();
  std::this_thread::sleep_for(80ms);
  require(observed->move_count() == count_after_stop,
          "worker does not call Move after StopMove");
  require(observed->stop_calls() >= 1, "backend StopMove is called");
}

void test_latest_velocity_replaces_blocked_target() {
  auto backend = std::make_unique<RecordingSportApi>();
  auto* observed = backend.get();
  observed->block_moves();
  auto api = go2_gateway::make_pumped_sport_api(std::move(backend), 20ms);

  require(api->Move(0.1F, 0.0F, 0.0F) == 0, "first Move is accepted");
  require(observed->wait_for_move_count(1, 250ms),
          "first Move reaches backend");
  require(api->Move(0.2F, 0.0F, 0.0F) == 0,
          "new Move replaces pending target");
  observed->release_moves();
  require(observed->wait_for_move_count(2, 250ms),
          "worker sends refreshed target");
  const auto [vx, vy, vyaw] = observed->move_at(1);
  require(std::fabs(vx - 0.2F) < 1e-6F && std::fabs(vy) < 1e-6F &&
              std::fabs(vyaw) < 1e-6F,
          "second backend call uses only latest velocity");
  require(api->StopMove() == 0, "StopMove succeeds");
}

void test_worker_error_is_reported_once() {
  auto backend = std::make_unique<RecordingSportApi>();
  auto* observed = backend.get();
  observed->set_move_result(37);
  auto api = go2_gateway::make_pumped_sport_api(std::move(backend), 20ms);

  require(api->Move(0.2F, 0.0F, 0.0F) == 0, "Move is queued");
  require(observed->wait_for_move_count(1, 250ms),
          "failing Move reaches backend");

  int error = 0;
  for (int attempt = 0; attempt < 20 && error == 0; ++attempt) {
    std::this_thread::sleep_for(10ms);
    error = api->PollError();
  }
  require(error == 37, "backend error is exposed by PollError");
  require(api->PollError() == 0, "worker error is consumed once");
}

}  // namespace

int main() {
  test_first_move_prepares_asynchronously_once();
  test_move_returns_while_backend_is_blocked();
  test_worker_repeats_and_stop_halts_refresh();
  test_latest_velocity_replaces_blocked_target();
  test_worker_error_is_reported_once();
  std::cout << "pumped_sport_api_test: PASS\n";
  return 0;
}
