#include <rclcpp/rclcpp.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>

#include <pcl/io/pcd_io.h>
#include <pcl/point_types.h>
#include <pcl/filters/statistical_outlier_removal.h>
#include <pcl/filters/passthrough.h>

#include <fstream>
#include <queue>

class PCDToOccupancyNode : public rclcpp::Node
{
public:
    PCDToOccupancyNode() : Node("pcd_to_occupancy")
    {
        declare_parameter<std::string>("pcd_file", "map.pcd");
        declare_parameter<std::string>("output_path", "");
        declare_parameter<double>("resolution", 0.05);
        declare_parameter<double>("z_min", 0.2);
        declare_parameter<double>("z_max", 2.0);
        declare_parameter<double>("padding", 1.0);
        declare_parameter<int>("sor_mean_k", 30);
        declare_parameter<double>("sor_stddev", 1.0);
        declare_parameter<int>("hit_threshold", 3);

        get_parameter("pcd_file", pcd_file_);
        get_parameter("output_path", output_path_);
        get_parameter("resolution", resolution_);
        get_parameter("z_min", z_min_);
        get_parameter("z_max", z_max_);
        get_parameter("padding", padding_);
        get_parameter("sor_mean_k", sor_mean_k_);
        get_parameter("sor_stddev", sor_stddev_);
        get_parameter("hit_threshold", hit_threshold_);

        cloud_.reset(new pcl::PointCloud<pcl::PointXYZ>);
        if (!loadPCD()) {
            rclcpp::shutdown();
            return;
        }

        rclcpp::QoS qos(1);
        qos.transient_local();
        map_pub_ = create_publisher<nav_msgs::msg::OccupancyGrid>("/map", qos);

        processAndBuildMap();

        if (!output_path_.empty()) {
            saveMapToFile(output_path_);
        }

        publish();

        // 所有工作已完成，通知 spin() 退出
        rclcpp::shutdown();
    }

private:
    std::string pcd_file_;
    std::string output_path_;
    double resolution_, z_min_, z_max_, padding_, sor_stddev_;
    int sor_mean_k_, hit_threshold_;

    pcl::PointCloud<pcl::PointXYZ>::Ptr cloud_;
    nav_msgs::msg::OccupancyGrid map_;
    rclcpp::Publisher<nav_msgs::msg::OccupancyGrid>::SharedPtr map_pub_;

    bool loadPCD()
    {
        if (pcl::io::loadPCDFile<pcl::PointXYZ>(pcd_file_, *cloud_) == -1) {
            RCLCPP_ERROR(get_logger(), "Failed to load PCD: %s", pcd_file_.c_str());
            return false;
        }
        RCLCPP_INFO(get_logger(), "Loaded PCD with %zu points", cloud_->size());
        return true;
    }

    void processAndBuildMap()
    {
        // 高度过滤
        pcl::PointCloud<pcl::PointXYZ>::Ptr cloud_z(new pcl::PointCloud<pcl::PointXYZ>);
        pcl::PassThrough<pcl::PointXYZ> pass;
        pass.setInputCloud(cloud_);
        pass.setFilterFieldName("z");
        pass.setFilterLimits(z_min_, z_max_);
        pass.filter(*cloud_z);
        RCLCPP_INFO(get_logger(), "After height filter: %zu points", cloud_z->size());

        // 统计去噪
        pcl::PointCloud<pcl::PointXYZ>::Ptr cloud_filtered(new pcl::PointCloud<pcl::PointXYZ>);
        pcl::StatisticalOutlierRemoval<pcl::PointXYZ> sor;
        sor.setInputCloud(cloud_z);
        sor.setMeanK(sor_mean_k_);
        sor.setStddevMulThresh(sor_stddev_);
        sor.filter(*cloud_filtered);
        RCLCPP_INFO(get_logger(), "After denoising: %zu points", cloud_filtered->size());

        // 计算 XY 边界
        double x_min = std::numeric_limits<double>::max(), y_min = x_min;
        double x_max = -std::numeric_limits<double>::max(), y_max = x_max;
        for (const auto &p : cloud_filtered->points) {
            x_min = std::min(x_min, (double)p.x);
            y_min = std::min(y_min, (double)p.y);
            x_max = std::max(x_max, (double)p.x);
            y_max = std::max(y_max, (double)p.y);
        }

        double map_xmin = x_min - padding_;
        double map_ymin = y_min - padding_;
        int width  = std::ceil((x_max - x_min + 2 * padding_) / resolution_);
        int height = std::ceil((y_max - y_min + 2 * padding_) / resolution_);

        RCLCPP_INFO(get_logger(),
            "Map: origin[%.2f, %.2f], size[%dx%d], bounds[%.1f-%.1f, %.1f-%.1f]",
            map_xmin, map_ymin, width, height, x_min, x_max, y_min, y_max);

        map_.header.frame_id = "map";
        map_.info.resolution = resolution_;
        map_.info.width  = width;
        map_.info.height = height;
        map_.info.origin.position.x = map_xmin;
        map_.info.origin.position.y = map_ymin;
        map_.info.origin.orientation.w = 1.0;
        map_.data.assign(width * height, -1);

        // 标记障碍物
        std::vector<int> counts(width * height, 0);
        for (const auto &p : cloud_filtered->points) {
            int gx = (p.x - map_xmin) / resolution_;
            int gy = (p.y - map_ymin) / resolution_;
            if (gx >= 0 && gx < width && gy >= 0 && gy < height) {
                counts[gy * width + gx]++;
            }
        }
        int occupied_count = 0;
        for (int i = 0; i < width * height; ++i) {
            if (counts[i] >= hit_threshold_) {
                map_.data[i] = 100;
                occupied_count++;
            }
        }
        RCLCPP_INFO(get_logger(), "Occupied cells: %d/%d (%.1f%%)",
            occupied_count, width * height, 100.0 * occupied_count / (width * height));

        // 泛洪填充自由空间（从地图原点 (0,0) 扩散）
        int start_x = (0.0 - map_xmin) / resolution_;
        int start_y = (0.0 - map_ymin) / resolution_;
        if (start_x >= 0 && start_x < width && start_y >= 0 && start_y < height) {
            std::queue<std::pair<int, int>> q;
            map_.data[start_y * width + start_x] = 0;
            q.push({start_x, start_y});
            int free_count = 0;
            const int dx[] = {1, -1, 0, 0};
            const int dy[] = {0, 0, 1, -1};
            while (!q.empty()) {
                auto [cx, cy] = q.front();
                q.pop();
                for (int i = 0; i < 4; i++) {
                    int nx = cx + dx[i], ny = cy + dy[i];
                    if (nx >= 0 && nx < width && ny >= 0 && ny < height) {
                        int idx = ny * width + nx;
                        if (map_.data[idx] == -1) {
                            map_.data[idx] = 0;
                            q.push({nx, ny});
                            free_count++;
                        }
                    }
                }
            }
            RCLCPP_INFO(get_logger(), "Free cells after flood fill: %d", free_count);
        }

        RCLCPP_INFO(get_logger(), "Map building complete!");
    }

    void saveMapToFile(const std::string &filename)
    {
        // 保存 .pgm（Y 轴翻转以符合 PGM 格式）
        std::ofstream pgm(filename + ".pgm", std::ios::binary);
        if (!pgm) {
            RCLCPP_ERROR(get_logger(), "Cannot open %s.pgm for writing", filename.c_str());
            return;
        }
        pgm << "P5\n" << map_.info.width << " " << map_.info.height << "\n255\n";
        for (int i = (int)map_.info.height - 1; i >= 0; --i) {
            for (int j = 0; j < (int)map_.info.width; ++j) {
                int idx = i * map_.info.width + j;
                uint8_t v = (map_.data[idx] == 0) ? 254 : (map_.data[idx] == 100) ? 0 : 205;
                pgm.write(reinterpret_cast<char *>(&v), 1);
            }
        }
        pgm.close();

        // 保存 .yaml
        std::ofstream yaml(filename + ".yaml");
        if (!yaml) {
            RCLCPP_ERROR(get_logger(), "Cannot open %s.yaml for writing", filename.c_str());
            return;
        }
        yaml << "image: " << filename << ".pgm\n"
             << "resolution: " << map_.info.resolution << "\n"
             << "origin: [" << map_.info.origin.position.x << ", "
             << map_.info.origin.position.y << ", 0.0]\n"
             << "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n";
        yaml.close();

        RCLCPP_INFO(get_logger(), "Map saved to %s.{pgm,yaml}", filename.c_str());
    }

    void publish()
    {
        map_.header.stamp = now();
        map_pub_->publish(map_);
        RCLCPP_INFO(get_logger(), "Published map to /map");
    }
};

int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<PCDToOccupancyNode>());
    rclcpp::shutdown();
    return 0;
}
