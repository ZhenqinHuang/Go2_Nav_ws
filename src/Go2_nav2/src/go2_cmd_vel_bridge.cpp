#include <algorithm>
#include <cmath>
#include <limits>

#include <geometry_msgs/msg/twist.hpp>
#include <rclcpp/rclcpp.hpp>

#include "common/ros2_sport_client.h"

class Go2CmdVelBridgeNode : public rclcpp::Node {
 public:
  Go2CmdVelBridgeNode()
      : Node("go2_cmd_vel_bridge"),
        sport_client_(this),
        last_cmd_time_(this->now()) {
    cmd_vel_topic_ =
        this->declare_parameter<std::string>("cmd_vel_topic", "/cmd_vel");
    max_vx_ = this->declare_parameter<double>("max_vx", 0.6);
    max_vy_ = this->declare_parameter<double>("max_vy", 0.4);
    max_vyaw_ = this->declare_parameter<double>("max_vyaw", 1.0);
    publish_rate_hz_ = this->declare_parameter<double>("publish_rate_hz", 50.0);
    cmd_timeout_sec_ = this->declare_parameter<double>("cmd_timeout_sec", 0.35);
    auto_stand_up_ = this->declare_parameter<bool>("auto_stand_up", false);
    stand_up_on_motion_ =
        this->declare_parameter<bool>("stand_up_on_motion", true);
    motion_deadband_ = this->declare_parameter<double>("motion_deadband", 0.03);
    stand_up_settle_sec_ =
        this->declare_parameter<double>("stand_up_settle_sec", 0.6);

    cmd_sub_ = this->create_subscription<geometry_msgs::msg::Twist>(
        cmd_vel_topic_, rclcpp::SystemDefaultsQoS(),
        [this](const geometry_msgs::msg::Twist::SharedPtr msg) {
          cmd_callback(msg);
        });

    const auto period_ms = std::max(1, static_cast<int>(1000.0 / publish_rate_hz_));
    timer_ = this->create_wall_timer(std::chrono::milliseconds(period_ms), [this]() {
      control_loop();
    });

    if (auto_stand_up_) {
      unitree_api::msg::Request req;
      sport_client_.StandUp(req);
      stand_up_last_time_ = this->now();
      stand_up_issued_ = true;
    }

    RCLCPP_INFO(this->get_logger(),
                "bridge ready: cmd topic=%s, max_vx=%.2f, max_vy=%.2f, "
                "max_vyaw=%.2f, timeout=%.2fs, rate=%.1fHz, deadband=%.2f",
                cmd_vel_topic_.c_str(), max_vx_, max_vy_, max_vyaw_,
                cmd_timeout_sec_, publish_rate_hz_, motion_deadband_);
  }

 private:
  static double clamp(double v, double lo, double hi) {
    return std::max(lo, std::min(v, hi));
  }

  static bool finite_or_zero(double &v) {
    if (!std::isfinite(v)) {
      v = 0.0;
      return false;
    }
    return true;
  }

  void cmd_callback(const geometry_msgs::msg::Twist::SharedPtr &msg) {
    double vx = msg->linear.x;
    double vy = msg->linear.y;
    double vyaw = msg->angular.z;

    const bool vx_ok = finite_or_zero(vx);
    const bool vy_ok = finite_or_zero(vy);
    const bool vyaw_ok = finite_or_zero(vyaw);
    if (!vx_ok || !vy_ok || !vyaw_ok) {
      RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 3000,
                           "cmd_vel has NaN/Inf, invalid fields replaced by 0");
    }

    target_vx_ = clamp(vx, -max_vx_, max_vx_);
    target_vy_ = clamp(vy, -max_vy_, max_vy_);
    target_vyaw_ = clamp(vyaw, -max_vyaw_, max_vyaw_);

    if (std::fabs(target_vx_) < motion_deadband_) {
      target_vx_ = 0.0;
    }
    if (std::fabs(target_vy_) < motion_deadband_) {
      target_vy_ = 0.0;
    }
    if (std::fabs(target_vyaw_) < motion_deadband_) {
      target_vyaw_ = 0.0;
    }

    last_cmd_time_ = this->now();
  }

  void control_loop() {
    unitree_api::msg::Request req;
    const double dt = (this->now() - last_cmd_time_).seconds();
    if (dt > cmd_timeout_sec_) {
      if (!timed_out_) {
        sport_client_.StopMove(req);
        timed_out_ = true;
        target_vx_ = 0.0;
        target_vy_ = 0.0;
        target_vyaw_ = 0.0;
        RCLCPP_WARN(this->get_logger(),
                    "cmd_vel timeout %.2fs reached, robot stopped", dt);
      }
      return;
    }

    timed_out_ = false;
    const bool has_motion_cmd = (std::fabs(target_vx_) > 0.0) ||
                                (std::fabs(target_vy_) > 0.0) ||
                                (std::fabs(target_vyaw_) > 0.0);

    if (stand_up_on_motion_ && has_motion_cmd && !stand_up_issued_) {
      sport_client_.StandUp(req);
      stand_up_last_time_ = this->now();
      stand_up_issued_ = true;
      RCLCPP_INFO(this->get_logger(),
                  "non-zero cmd_vel detected, send StandUp before moving");
      return;
    }

    if (stand_up_issued_ &&
        (this->now() - stand_up_last_time_).seconds() < stand_up_settle_sec_) {
      return;
    }

    sport_client_.Move(req, static_cast<float>(target_vx_),
                       static_cast<float>(target_vy_),
                       static_cast<float>(target_vyaw_));
  }

  SportClient sport_client_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_sub_;
  rclcpp::TimerBase::SharedPtr timer_;

  std::string cmd_vel_topic_;
  double max_vx_{0.6};
  double max_vy_{0.4};
  double max_vyaw_{1.0};
  double publish_rate_hz_{50.0};
  double cmd_timeout_sec_{0.35};
  bool auto_stand_up_{false};
  bool stand_up_on_motion_{true};
  double motion_deadband_{0.03};
  double stand_up_settle_sec_{0.6};

  double target_vx_{0.0};
  double target_vy_{0.0};
  double target_vyaw_{0.0};
  bool timed_out_{true};
  bool stand_up_issued_{false};
  rclcpp::Time last_cmd_time_;
  rclcpp::Time stand_up_last_time_{0, 0, RCL_ROS_TIME};
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<Go2CmdVelBridgeNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
