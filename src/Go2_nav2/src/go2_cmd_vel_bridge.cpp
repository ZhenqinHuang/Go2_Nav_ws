#include <algorithm>
#include <cmath>
#include <limits>

#include <geometry_msgs/msg/twist.hpp>
#include <nav_msgs/msg/odometry.hpp>
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
    // Go2 sport API 不支持横向移动，默认强制为 0；
    // 即使 yaml 加载失败或参数名拼错，也不会让狗扭腰乱走
    max_vy_ = this->declare_parameter<double>("max_vy", 0.0);
    max_vyaw_ = this->declare_parameter<double>("max_vyaw", 1.0);
    publish_rate_hz_ = this->declare_parameter<double>("publish_rate_hz", 50.0);
    cmd_timeout_sec_ = this->declare_parameter<double>("cmd_timeout_sec", 0.35);
    auto_stand_up_ = this->declare_parameter<bool>("auto_stand_up", false);
    stand_up_on_motion_ =
        this->declare_parameter<bool>("stand_up_on_motion", true);
    motion_deadband_ = this->declare_parameter<double>("motion_deadband", 0.03);
    stand_up_settle_sec_ =
        this->declare_parameter<double>("stand_up_settle_sec", 0.6);
    // EMA 平滑系数：1=无平滑，0.85=轻量滤尖峰，0.5=强平滑（会引入滞后）
    vyaw_alpha_ = this->declare_parameter<double>("vyaw_smooth_alpha", 0.85);
    localization_guard_enabled_ =
        this->declare_parameter<bool>("localization_guard_enabled", false);
    localization_topic_ =
        this->declare_parameter<std::string>("localization_topic", "/map_to_odom");
    localization_timeout_sec_ =
        this->declare_parameter<double>("localization_timeout_sec", 2.5);
    correction_pause_sec_ =
        this->declare_parameter<double>("correction_pause_sec", 1.0);
    correction_pause_delta_xy_ =
        this->declare_parameter<double>("correction_pause_delta_xy", 0.12);
    correction_pause_delta_yaw_ =
        this->declare_parameter<double>("correction_pause_delta_yaw", 0.12);

    cmd_sub_ = this->create_subscription<geometry_msgs::msg::Twist>(
        cmd_vel_topic_, rclcpp::SystemDefaultsQoS(),
        [this](const geometry_msgs::msg::Twist::SharedPtr msg) {
          cmd_callback(msg);
        });

    if (localization_guard_enabled_) {
      loc_sub_ = this->create_subscription<nav_msgs::msg::Odometry>(
          localization_topic_, rclcpp::QoS(10),
          [this](const nav_msgs::msg::Odometry::SharedPtr msg) {
            localization_callback(msg);
          });
    }

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
                "max_vyaw=%.2f, timeout=%.2fs, rate=%.1fHz, deadband=%.2f, "
                "loc_guard=%s",
                cmd_vel_topic_.c_str(), max_vx_, max_vy_, max_vyaw_,
                cmd_timeout_sec_, publish_rate_hz_, motion_deadband_,
                localization_guard_enabled_ ? "true" : "false");
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

  static double yaw_from_quat(const geometry_msgs::msg::Quaternion &q) {
    return std::atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z));
  }

  static double normalize_angle(double a) {
    constexpr double kPi = 3.14159265358979323846;
    while (a > kPi) a -= 2.0 * kPi;
    while (a < -kPi) a += 2.0 * kPi;
    return a;
  }

  void localization_callback(const nav_msgs::msg::Odometry::SharedPtr &msg) {
    const auto &p = msg->pose.pose.position;
    const double yaw = yaw_from_quat(msg->pose.pose.orientation);

    if (has_last_localization_pose_) {
      const double dx = p.x - last_localization_x_;
      const double dy = p.y - last_localization_y_;
      const double delta_xy = std::hypot(dx, dy);
      const double delta_yaw =
          std::fabs(normalize_angle(yaw - last_localization_yaw_));

      if (delta_xy > correction_pause_delta_xy_ ||
          delta_yaw > correction_pause_delta_yaw_) {
        localization_pause_until_sec_ =
            std::max(localization_pause_until_sec_,
                     this->now().seconds() + correction_pause_sec_);
        RCLCPP_WARN(this->get_logger(),
                    "localization correction detected (dxy=%.3fm, dyaw=%.3frad), "
                    "pause motion for %.2fs",
                    delta_xy, delta_yaw, correction_pause_sec_);
      }
    }

    last_localization_x_ = p.x;
    last_localization_y_ = p.y;
    last_localization_yaw_ = yaw;
    has_last_localization_pose_ = true;
    last_localization_time_sec_ = this->now().seconds();
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
    double raw_vyaw = clamp(vyaw, -max_vyaw_, max_vyaw_);

    if (std::fabs(target_vx_) < motion_deadband_) target_vx_ = 0.0;
    if (std::fabs(target_vy_) < motion_deadband_) target_vy_ = 0.0;
    if (std::fabs(raw_vyaw)   < motion_deadband_) raw_vyaw   = 0.0;

    // EMA 平滑角速度：新指令与历史值加权混合，抑制控制器帧间 vtheta 跳变
    target_vyaw_ = vyaw_alpha_ * raw_vyaw + (1.0 - vyaw_alpha_) * target_vyaw_;

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

    if (localization_guard_enabled_ && localization_blocked()) {
      if (!localization_stop_active_) {
        sport_client_.StopMove(req);
        localization_stop_active_ = true;
        target_vx_ = 0.0;
        target_vy_ = 0.0;
        target_vyaw_ = 0.0;
      }
      return;
    }

    timed_out_ = false;
    localization_stop_active_ = false;
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

  bool localization_blocked() {
    const double now_sec = this->now().seconds();
    if (!has_last_localization_pose_) {
      RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 3000,
                           "waiting for localization topic %s before motion",
                           localization_topic_.c_str());
      return true;
    }

    const double loc_age = now_sec - last_localization_time_sec_;
    if (loc_age > localization_timeout_sec_) {
      RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 3000,
                           "localization stale for %.2fs (> %.2fs), motion paused",
                           loc_age, localization_timeout_sec_);
      return true;
    }

    if (now_sec < localization_pause_until_sec_) {
      RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 1000,
                           "localization correction settling, motion paused");
      return true;
    }

    return false;
  }

  SportClient sport_client_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_sub_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr loc_sub_;
  rclcpp::TimerBase::SharedPtr timer_;

  std::string cmd_vel_topic_;
  double max_vx_{0.6};
  double max_vy_{0.0};
  double max_vyaw_{1.0};
  double publish_rate_hz_{50.0};
  double cmd_timeout_sec_{0.35};
  bool auto_stand_up_{false};
  bool stand_up_on_motion_{true};
  double motion_deadband_{0.03};
  double stand_up_settle_sec_{0.6};
  bool localization_guard_enabled_{false};
  std::string localization_topic_{"/map_to_odom"};
  double localization_timeout_sec_{2.5};
  double correction_pause_sec_{1.0};
  double correction_pause_delta_xy_{0.12};
  double correction_pause_delta_yaw_{0.12};

  double vyaw_alpha_{0.5};
  double target_vx_{0.0};
  double target_vy_{0.0};
  double target_vyaw_{0.0};
  bool timed_out_{true};
  bool localization_stop_active_{false};
  bool stand_up_issued_{false};
  rclcpp::Time last_cmd_time_;
  rclcpp::Time stand_up_last_time_{0, 0, RCL_ROS_TIME};
  bool has_last_localization_pose_{false};
  double last_localization_time_sec_{0.0};
  double localization_pause_until_sec_{0.0};
  double last_localization_x_{0.0};
  double last_localization_y_{0.0};
  double last_localization_yaw_{0.0};
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<Go2CmdVelBridgeNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
