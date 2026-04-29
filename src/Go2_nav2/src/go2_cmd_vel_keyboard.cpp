#include <sys/select.h>
#include <termios.h>
#include <unistd.h>

#include <chrono>
#include <cmath>
#include <iostream>

#include <geometry_msgs/msg/twist.hpp>
#include <rclcpp/rclcpp.hpp>

class TerminalRawMode {
 public:
  TerminalRawMode() {
    tcgetattr(STDIN_FILENO, &old_term_);
    termios raw = old_term_;
    raw.c_lflag &= ~(ICANON | ECHO);
    raw.c_cc[VMIN] = 0;
    raw.c_cc[VTIME] = 0;
    tcsetattr(STDIN_FILENO, TCSANOW, &raw);
  }

  ~TerminalRawMode() { tcsetattr(STDIN_FILENO, TCSANOW, &old_term_); }

 private:
  termios old_term_{};
};

class Go2CmdVelKeyboardNode : public rclcpp::Node {
 public:
  Go2CmdVelKeyboardNode() : Node("go2_cmd_vel_keyboard") {
    cmd_vel_topic_ =
        this->declare_parameter<std::string>("cmd_vel_topic", "/cmd_vel");
    max_vx_ = this->declare_parameter<double>("max_vx", 0.6);
    max_vy_ = this->declare_parameter<double>("max_vy", 0.4);
    max_vyaw_ = this->declare_parameter<double>("max_vyaw", 1.0);
    publish_rate_hz_ = this->declare_parameter<double>("publish_rate_hz", 30.0);
    key_timeout_sec_ = this->declare_parameter<double>("key_timeout_sec", 1.00);

    cmd_pub_ = this->create_publisher<geometry_msgs::msg::Twist>(
        cmd_vel_topic_, rclcpp::SystemDefaultsQoS());

    print_help();
    const auto period_ms = std::max(1, static_cast<int>(1000.0 / publish_rate_hz_));
    timer_ = this->create_wall_timer(std::chrono::milliseconds(period_ms), [this]() {
      update_key_input();
      publish_cmd_vel();
    });
  }

 private:
  void print_help() const {
    std::cout << "\nGo2 cmd_vel Keyboard Teleop (focus this terminal)\n"
              << "  w/s : forward/backward\n"
              << "  a/d : left/right strafe\n"
              << "  q/e : turn left/right\n"
              << "  space or z : stop\n"
              << "  +/- : increase/decrease speed scale\n"
              << "  Ctrl+C : exit\n\n";
  }

  void update_key_input() {
    fd_set set;
    FD_ZERO(&set);
    FD_SET(STDIN_FILENO, &set);
    timeval timeout{};
    timeout.tv_sec = 0;
    timeout.tv_usec = 0;

    const int rv = select(STDIN_FILENO + 1, &set, nullptr, nullptr, &timeout);
    if (rv <= 0 || !FD_ISSET(STDIN_FILENO, &set)) {
      return;
    }

    char c = 0;
    if (read(STDIN_FILENO, &c, 1) <= 0) {
      return;
    }

    const double base_v = 0.45 * speed_scale_;
    const double base_yaw = 0.80 * speed_scale_;

    switch (c) {
      case 'w':
      case 'W':
        vx_ = base_v;
        vy_ = 0.0;
        vyaw_ = 0.0;
        break;
      case 's':
      case 'S':
        vx_ = -base_v;
        vy_ = 0.0;
        vyaw_ = 0.0;
        break;
      case 'a':
      case 'A':
        vx_ = 0.0;
        vy_ = base_v;
        vyaw_ = 0.0;
        break;
      case 'd':
      case 'D':
        vx_ = 0.0;
        vy_ = -base_v;
        vyaw_ = 0.0;
        break;
      case 'q':
      case 'Q':
        vx_ = 0.0;
        vy_ = 0.0;
        vyaw_ = base_yaw;
        break;
      case 'e':
      case 'E':
        vx_ = 0.0;
        vy_ = 0.0;
        vyaw_ = -base_yaw;
        break;
      case ' ':
      case 'z':
      case 'Z':
        vx_ = 0.0;
        vy_ = 0.0;
        vyaw_ = 0.0;
        break;
      case '+':
      case '=':
        speed_scale_ = std::fmin(speed_scale_ + 0.1, 1.5);
        RCLCPP_INFO(this->get_logger(), "speed scale: %.2f", speed_scale_);
        break;
      case '-':
      case '_':
        speed_scale_ = std::fmax(speed_scale_ - 0.1, 0.2);
        RCLCPP_INFO(this->get_logger(), "speed scale: %.2f", speed_scale_);
        break;
      default:
        break;
    }

    vx_ = std::max(-max_vx_, std::min(vx_, max_vx_));
    vy_ = std::max(-max_vy_, std::min(vy_, max_vy_));
    vyaw_ = std::max(-max_vyaw_, std::min(vyaw_, max_vyaw_));
    last_key_time_ = this->now();
  }

  void publish_cmd_vel() {
    if ((this->now() - last_key_time_).seconds() > key_timeout_sec_) {
      vx_ = 0.0;
      vy_ = 0.0;
      vyaw_ = 0.0;
    }

    geometry_msgs::msg::Twist cmd{};
    cmd.linear.x = vx_;
    cmd.linear.y = vy_;
    cmd.angular.z = vyaw_;
    cmd_pub_->publish(cmd);
  }

  std::string cmd_vel_topic_;
  double max_vx_{0.6};
  double max_vy_{0.4};
  double max_vyaw_{1.0};
  double publish_rate_hz_{20.0};
  double key_timeout_sec_{0.30};

  double vx_{0.0};
  double vy_{0.0};
  double vyaw_{0.0};
  double speed_scale_{1.0};
  rclcpp::Time last_key_time_{0, 0, RCL_ROS_TIME};

  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr cmd_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  TerminalRawMode raw_mode;
  auto node = std::make_shared<Go2CmdVelKeyboardNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
