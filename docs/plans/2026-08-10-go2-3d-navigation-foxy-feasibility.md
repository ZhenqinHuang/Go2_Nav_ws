# Go2 3D Navigation Foxy Feasibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不控制机器人运动、不中断现有 Nav2 部署的前提下，证明 KISS-Matcher、small_gicp、SCAN-Planner 和 PCT Planner 能在 Jetson Orin NX + ROS 2 Foxy 上用真实 Go2 数据满足 B 阶段集成的最低条件。

**Architecture:** 本计划只建设一个隔离的可行性工作区、固定上游版本、最小注册探针、SCAN 影子链路和 PCT 离线链路。现有 FAST-LIO2/Nav2/Unitree 控制链保持不变；只有全部闸门通过后，才编写正式定位、全局规划、局部规划和安全监督节点。

**Tech Stack:** Ubuntu 20.04, ROS 2 Foxy, JetPack/CUDA, C++17, Python 3.8, colcon/ament, pytest, rosbag2, PCL, KISS-Matcher, small_gicp, SCAN-Planner, PCT Planner, tegrastats.

---

## 执行约束

- 实机路径统一使用 `/home/nvidia/Go2_Nav_ws_3dnav`，通过 Git worktree 与现有 `/home/nvidia/Go2_Nav_ws` 隔离。
- 在本计划结束前，禁止发布到现有 `/cmd_vel`、Unitree Sport API 或 UDP 运动网关。
- PCT 只做离线 Tomogram 和全局路线验证，不在此阶段移植成常驻 ROS 2 节点。
- SCAN 所有控制输出必须 remap 到 `/go2_3d_shadow/cmd_vel`，且该话题没有运动执行订阅者。
- 不提前引入地点检索、Elevation Mapping CuPy、楼梯策略或 Humble 兼容层。
- 所有上游依赖必须固定完整 commit SHA；Foxy 补丁只处理实际复现的编译/运行差异。
- 每个任务开始前使用 `@superpowers:test-driven-development`；每次提交前使用 `@superpowers:verification-before-completion`。

## 闸门指标

只有以下条件全部满足，结论才为 `GO`：

| 闸门 | 最低条件 |
|---|---|
| 数据 | 一份包含 MID360、FAST-LIO2 odom/点云、TF 和 D435i 深度的代表性 rosbag，可重复回放 |
| KISS + small_gicp | 20 个代表性初始位姿中至少 19 个成功；成功样本误差不高于 0.20 m / 5° |
| SCAN | Foxy 可构建；`navi_mode=3` 能接收 `initial_path`；真实 rosbag 下持续产生局部规划结果；不连接真实运动输出 |
| PCT | 能从真实基准 PCD 生成 Tomogram，并在至少 5 组起终点中输出有效三维路线 |
| 资源 | FAST-LIO2 + SCAN 影子链路运行时无 OOM、无持续 backlog；局部规划结果 95 分位延迟不高于 200 ms |
| 可重复性 | 同一输入连续运行 3 次，成功/失败状态一致，关键指标差异有记录 |

指标不通过时记录 `NO-GO` 或 `CONDITIONAL-GO`，不得通过放宽安全阈值掩盖问题。

### Task 1: 建立隔离 worktree 与只读基线

**Files:**
- Create: `scripts/3d_nav/capture_foxy_baseline.sh`
- Create: `test/test_3d_nav_baseline_script.py`
- Create at runtime: `artifacts/3d_nav_feasibility/baseline/`

**Step 1: 创建隔离 worktree**

Run on Jetson:

```bash
git -C /home/nvidia/Go2_Nav_ws worktree add \
  /home/nvidia/Go2_Nav_ws_3dnav \
  -b codex/3d-nav-foxy-feasibility
cd /home/nvidia/Go2_Nav_ws_3dnav
```

Expected: 新 worktree 指向包含本计划的提交；原工作区状态不变。

**Step 2: 写失败的脚本契约测试**

```python
# test/test_3d_nav_baseline_script.py
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/3d_nav/capture_foxy_baseline.sh"


def test_baseline_capture_is_read_only_and_collects_required_evidence():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "ros2 doctor --report" in text
    assert "ros2 topic list -t" in text
    assert "ros2 pkg list" in text
    assert "tegrastats" in text
    assert "git status --short" in text
    assert "apt upgrade" not in text
    assert "rm -rf" not in text
```

**Step 3: 运行测试并确认失败**

Run:

```bash
cd /home/nvidia/Go2_Nav_ws_3dnav
python3 -m pytest test/test_3d_nav_baseline_script.py -q
```

Expected: FAIL，原因是脚本不存在。

**Step 4: 实现最小只读采集脚本**

脚本必须只创建 `artifacts/3d_nav_feasibility/baseline/<timestamp>/`，并分别保存：系统/JetPack/CUDA、ROS doctor、topic 与类型、package 列表、TF 摘要、现有三个工作区 Git 状态、10 秒 `tegrastats`。不得安装、升级、停止或重启服务。

**Step 5: 验证并采集基线**

Run:

```bash
python3 -m pytest test/test_3d_nav_baseline_script.py -q
bash scripts/3d_nav/capture_foxy_baseline.sh
find artifacts/3d_nav_feasibility/baseline -maxdepth 2 -type f -size +0c
```

Expected: pytest PASS；每类证据文件存在且非空。

**Step 6: 提交**

```bash
git add scripts/3d_nav/capture_foxy_baseline.sh test/test_3d_nav_baseline_script.py
git commit -m "test: capture foxy navigation baseline"
```

### Task 2: 固定上游版本与许可边界

**Files:**
- Create: `manifests/go2_3d_nav_foxy.repos`
- Create: `manifests/go2_3d_nav_versions.lock`
- Create: `docs/third_party/go2-3d-navigation.md`
- Create: `test/test_3d_nav_dependency_manifest.py`

**Step 1: 写失败的依赖契约测试**

```python
# test/test_3d_nav_dependency_manifest.py
import re
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_all_selected_dependencies_are_pinned_to_full_commits():
    data = yaml.safe_load((ROOT / "manifests/go2_3d_nav_foxy.repos").read_text())
    repos = data["repositories"]
    assert set(repos) == {
        "src/vendor/kiss_matcher",
        "src/vendor/small_gicp",
        "src/vendor/scan_planner",
        "third_party/pct_planner",
    }
    for repo in repos.values():
        assert repo["type"] == "git"
        assert repo["url"].startswith("https://github.com/")
        assert re.fullmatch(r"[0-9a-f]{40}", repo["version"])


def test_license_notes_name_the_pct_distribution_risk():
    text = (ROOT / "docs/third_party/go2-3d-navigation.md").read_text()
    assert "PCT Planner" in text
    assert "GPLv2" in text
    assert "commercial" in text.lower()
```

**Step 2: 运行测试并确认失败**

Run: `python3 -m pytest test/test_3d_nav_dependency_manifest.py -q`

Expected: FAIL，manifest 和许可说明尚不存在。

**Step 3: 记录精确版本**

从以下官方仓库解析当前选定 commit，写入 `.repos`，禁止使用 `main`、`master` 或 branch 名：

- `https://github.com/MIT-SPARK/KISS-Matcher.git`
- `https://github.com/koide3/small_gicp.git`
- `https://github.com/wuyi2121/SCAN-Planner.git` 的 `ros2-community` 分支对应 commit
- `https://github.com/byangw/PCT_planner.git`

`go2_3d_nav_versions.lock` 同时记录 commit、采集日期、许可证、原始分支和本地补丁 SHA-256。

**Step 4: 验证 manifest 并导入**

Run:

```bash
python3 -m pytest test/test_3d_nav_dependency_manifest.py -q
vcs validate < manifests/go2_3d_nav_foxy.repos
vcs import . < manifests/go2_3d_nav_foxy.repos
vcs status src/vendor third_party/pct_planner
```

Expected: tests PASS；四个仓库处于指定 detached commit，无隐式更新。

**Step 5: 提交**

只提交 manifest、lock 和许可说明；上游 checkout 不纳入本仓库 Git 索引。

```bash
git add manifests/go2_3d_nav_foxy.repos manifests/go2_3d_nav_versions.lock \
  docs/third_party/go2-3d-navigation.md test/test_3d_nav_dependency_manifest.py
git commit -m "build: pin 3d navigation feasibility dependencies"
```

### Task 3: 建立可重复的 Foxy 构建探针

**Files:**
- Create: `scripts/3d_nav/build_foxy_feasibility.sh`
- Create: `compat/foxy/scan_planner/README.md`
- Create as failures require: `compat/foxy/scan_planner/*.patch`
- Create: `test/test_3d_nav_foxy_build_script.py`

**Step 1: 写失败的构建脚本测试**

测试必须断言脚本：source `/opt/ros/foxy/setup.bash`；只构建 `kiss_matcher`、`small_gicp` 和 SCAN 相关包；使用 `--symlink-install`；把日志写入 `artifacts/3d_nav_feasibility/build/`；不运行 apt upgrade；不删除现有 `/home/nvidia/Go2_Nav_ws` 的 build/install/log。

**Step 2: 运行测试并确认失败**

Run: `python3 -m pytest test/test_3d_nav_foxy_build_script.py -q`

Expected: FAIL，构建脚本不存在。

**Step 3: 实现并运行首次构建**

Run:

```bash
bash scripts/3d_nav/build_foxy_feasibility.sh
```

Expected: 首次结果允许 FAIL，但必须完整保存首个编译错误和环境信息。

**Step 4: 只修复已经发生的 Foxy 差异**

对每个上游修改执行：

1. 保存失败日志；
2. 写最小补丁；
3. 将补丁放到 `compat/foxy/scan_planner/`；
4. 在 `README.md` 记录上游文件、失败信息、Foxy/Humble API 差异和删除条件；
5. 从干净指定 commit 应用补丁并重新构建。

不得为了“以后可能需要”修改 launch 或 API。

**Step 5: 验证干净重建**

Run:

```bash
python3 -m pytest test/test_3d_nav_foxy_build_script.py -q
bash scripts/3d_nav/build_foxy_feasibility.sh --clean
source install/setup.bash
ros2 pkg executables | grep -E 'kiss|gicp|scan'
```

Expected: test PASS；干净构建 exit 0；所需 SCAN 可执行文件可见。

**Step 6: 提交**

```bash
git add scripts/3d_nav/build_foxy_feasibility.sh compat/foxy/scan_planner \
  test/test_3d_nav_foxy_build_script.py
git commit -m "build: prove selected planners build on foxy"
```

### Task 4: 实现 KISS + small_gicp 注册探针

**Files:**
- Create: `src/Go2_navigation/go2_registration_probe/CMakeLists.txt`
- Create: `src/Go2_navigation/go2_registration_probe/package.xml`
- Create: `src/Go2_navigation/go2_registration_probe/include/go2_registration_probe/registration_pipeline.hpp`
- Create: `src/Go2_navigation/go2_registration_probe/src/registration_pipeline.cpp`
- Create: `src/Go2_navigation/go2_registration_probe/src/registration_probe.cpp`
- Create: `src/Go2_navigation/go2_registration_probe/test/test_registration_pipeline.cpp`

**Step 1: 写失败的合成点云测试**

测试生成非对称三维点集，施加已知 1.0 m 平移和 30° yaw，调用我们自己的接口：

```cpp
RegistrationResult registerClouds(
    const Eigen::Matrix4d& initial_guess,
    const PointCloud& source,
    const PointCloud& target);
```

断言：KISS 粗配准收敛；small_gicp 精配准收敛；最终平移误差 `< 0.05 m`、yaw 误差 `< 1.0°`；结果包含 coarse/fine 耗时、fitness、inlier ratio 和拒绝原因。

**Step 2: 运行测试并确认失败**

Run:

```bash
colcon build --packages-select go2_registration_probe --cmake-args -DBUILD_TESTING=ON
```

Expected: FAIL，包或接口不存在。

**Step 3: 实现最小算法封装**

- KISS-Matcher 仅负责粗配准；
- small_gicp 只接收 KISS 输出作为初值并精配准；
- CLI 输入 `--source`、`--target`、可选 `--initial-pose`，输出单行 JSON；
- CLI 不发布 TF、不启动 ROS graph、不控制机器人；
- 所有阈值通过命令行参数传入并原样写入 JSON。

**Step 4: 验证合成测试**

Run:

```bash
colcon build --packages-select go2_registration_probe --cmake-args -DBUILD_TESTING=ON
colcon test --packages-select go2_registration_probe --event-handlers console_direct+
colcon test-result --verbose
```

Expected: 0 failures。

**Step 5: 用真实子图建立 20 个试验样本**

Create runtime-only dataset:

```text
artifacts/3d_nav_feasibility/registration/
  target_map.pcd
  cases.yaml
  source_01.pcd ... source_20.pcd
  results.jsonl
```

样本覆盖不同房间、走廊、正反朝向、局部遮挡和至少两个相似结构位置。真实答案来自人工标定/已验证 TF，不得用被测算法输出充当真值。

**Step 6: 运行闸门并提交代码**

Run: `python3 scripts/3d_nav/evaluate_registration.py --cases artifacts/3d_nav_feasibility/registration/cases.yaml`

Expected: 至少 19/20 成功；成功样本误差不高于 0.20 m / 5°。失败时先记录，不修改闸门。

```bash
git add src/Go2_navigation/go2_registration_probe scripts/3d_nav/evaluate_registration.py
git commit -m "feat: add coarse-to-fine registration feasibility probe"
```

### Task 5: 录制并校验代表性 rosbag

**Files:**
- Create: `config/3d_nav/feasibility_topics.yaml`
- Create: `scripts/3d_nav/validate_feasibility_bag.py`
- Create: `test/test_feasibility_bag_validator.py`
- Create at runtime: `artifacts/3d_nav_feasibility/bags/b_scenario_01/`

**Step 1: 写失败的 bag 元数据测试**

用临时 SQLite metadata fixture 验证缺少以下任一输入时返回非零：FAST-LIO2 odom、注册点云/机体系点云、`/tf`、`/tf_static`、D435i 对齐深度或深度点云。验证时间倒退、最大间隔超限和 frame 为空会被报告。

**Step 2: 运行测试并确认失败**

Run: `python3 -m pytest test/test_feasibility_bag_validator.py -q`

Expected: FAIL，validator 不存在。

**Step 3: 实现最小 validator**

配置文件只定义逻辑输入到实际 topic 的映射和最低频率；validator 输出 JSON，字段固定为 `valid`、`duration_s`、`topics`、`missing`、`stale`、`time_regressions`、`frames`。

**Step 4: 录制安全场景**

机器人由人工遥控低速通过：平地、坡道、门槛、坑边替代物、低矮障碍、悬空横杆、静态阻塞和缓慢横穿障碍。此时新算法不连接控制链。

Run:

```bash
python3 scripts/3d_nav/validate_feasibility_bag.py \
  --config config/3d_nav/feasibility_topics.yaml \
  --bag artifacts/3d_nav_feasibility/bags/b_scenario_01
```

Expected: `valid: true`；每个逻辑输入满足频率/时间/frame 约束。

**Step 5: 验证并提交工具**

```bash
python3 -m pytest test/test_feasibility_bag_validator.py -q
git add config/3d_nav/feasibility_topics.yaml scripts/3d_nav/validate_feasibility_bag.py \
  test/test_feasibility_bag_validator.py
git commit -m "test: define repeatable 3d navigation bag contract"
```

rosbag 与生成的运行日志不得提交到 Git；只记录 SHA-256、时长、采集配置和存放位置。

### Task 6: 建立 SCAN Foxy 影子链路

**Files:**
- Create: `src/Go2_navigation/go2_3d_nav_bringup/CMakeLists.txt`
- Create: `src/Go2_navigation/go2_3d_nav_bringup/package.xml`
- Create: `src/Go2_navigation/go2_3d_nav_bringup/launch/scan_shadow.launch.py`
- Create: `src/Go2_navigation/go2_3d_nav_bringup/config/scan_shadow.yaml`
- Create: `src/Go2_navigation/go2_3d_nav_bringup/test/test_scan_shadow_contract.py`
- Create: `scripts/3d_nav/publish_test_initial_path.py`

**Step 1: 写失败的 launch 契约测试**

测试直接读取 launch/config 并断言：

- `navi_mode` 固定为 `3`；
- FAST-LIO2 odom/点云通过 remap 接入 SCAN 所需输入；
- 全局路线接到 `initial_path`；
- 所有控制输出 remap 到 `/go2_3d_shadow/cmd_vel`；
- launch 参数 `shadow_mode` 默认为 `true`，为 `true` 时不启动任何 Unitree/UDP/Nav2 执行节点；
- namespace 为 `/go2_3d_shadow`，避免污染现有节点。

**Step 2: 运行测试并确认失败**

Run: `python3 -m pytest src/Go2_navigation/go2_3d_nav_bringup/test/test_scan_shadow_contract.py -q`

Expected: FAIL，bringup 包不存在。

**Step 3: 实现最薄 launch 与配置**

不修改 SCAN 算法。只通过 include、参数和 remap 适配：

```text
FAST-LIO2 odom/cloud + optional D435i aligned depth
  -> SCAN expected inputs
/go2_3d_shadow/initial_path
  -> SCAN initial_path (navi_mode=3)
SCAN control output
  -> /go2_3d_shadow/cmd_vel (无人订阅运动执行)
```

`publish_test_initial_path.py` 发布一个短 `nav_msgs/Path`，frame 和时间戳来自 bag 的 TF，不硬编码 `map` 到传感器变换。

**Step 4: 验证 ROS graph 无运动连接**

Run:

```bash
source install/setup.bash
ros2 launch go2_3d_nav_bringup scan_shadow.launch.py shadow_mode:=true
ros2 node info /go2_3d_shadow/scan_planner
ros2 topic info /cmd_vel -v
ros2 topic info /go2_3d_shadow/cmd_vel -v
```

Expected: `/cmd_vel` 没有来自新链路的 publisher；影子 cmd_vel 没有运动执行 subscriber。

**Step 5: 回放真实 bag**

在 `--clock` 下回放 Task 5 bag，发布 test initial path，记录 SCAN 输入频率、输出频率、规划延迟、无解次数和进程内存。连续运行三次。

Expected: 三次都接收 `initial_path` 并持续生成局部结果；无真实运动输出；异常退出为 0。

**Step 6: 提交**

```bash
git add src/Go2_navigation/go2_3d_nav_bringup scripts/3d_nav/publish_test_initial_path.py
git commit -m "feat: add isolated scan planner shadow launch"
```

### Task 7: 验证 PCT 独立离线链路

**Files:**
- Create: `scripts/3d_nav/run_pct_offline.sh`
- Create: `scripts/3d_nav/validate_pct_route.py`
- Create: `test/test_pct_offline_contract.py`
- Create at runtime: `artifacts/3d_nav_feasibility/pct/`

**Step 1: 写失败的离线契约测试**

测试断言：脚本接收显式 `--pcd`、`--scene`、`--output-dir`；输出目录必须位于 `artifacts/3d_nav_feasibility/pct/`；不启动 ROS 1 master；不写入源 PCD 目录；保存 Tomogram、路线、参数、stdout/stderr 和耗时。

**Step 2: 运行测试并确认失败**

Run: `python3 -m pytest test/test_pct_offline_contract.py -q`

Expected: FAIL，脚本不存在。

**Step 3: 先运行 PCT 官方示例**

在 `third_party/pct_planner` 内构建官方 third-party/planner，运行官方示例场景。若 ROS 1 仅用于 RViz 发布，则增加最小 patch 关闭可视化并保留文件输出；不要在 Foxy 系统安装完整 Noetic desktop。

Expected: 官方 Tomogram 和路线文件成功生成。否则记录明确阻塞点并停止 PCT 集成工作。

**Step 4: 实现薄 CLI 包装与路线校验**

`validate_pct_route.py` 至少检查：点数大于 1、坐标有限、相邻点距离不超配置上限、起终点误差、路径长度、最低/最高高度和生成耗时。输出 JSON，不依赖 ROS 1 message runtime。

**Step 5: 用真实 PCD 运行 5 组起终点**

场景覆盖平层绕障、坡道、净空限制、不可达目标和 B 阶段禁止楼梯。每组保存输入与结果摘要；不可达目标必须明确返回失败，不能输出穿障路径。

Expected: 4 个可达用例输出有效路线；1 个不可达用例被拒绝；楼梯连接不被 B 路线选择。

**Step 6: 验证并提交包装工具**

```bash
python3 -m pytest test/test_pct_offline_contract.py -q
git add scripts/3d_nav/run_pct_offline.sh scripts/3d_nav/validate_pct_route.py \
  test/test_pct_offline_contract.py
git commit -m "test: prove pct offline planning on go2 map"
```

### Task 8: 运行组合资源与延迟基准

**Files:**
- Create: `scripts/3d_nav/run_shadow_benchmark.sh`
- Create: `scripts/3d_nav/summarize_shadow_benchmark.py`
- Create: `test/test_shadow_benchmark_summary.py`
- Create at runtime: `artifacts/3d_nav_feasibility/benchmark/`

**Step 1: 写失败的统计测试**

使用固定 CSV fixture 验证摘要正确计算 CPU、GPU、RAM、温度、输入频率、规划频率、延迟 p50/p95/p99、deadline miss 和进程退出码。缺列或采样不足必须失败，不能默认为 0。

**Step 2: 运行测试并确认失败**

Run: `python3 -m pytest test/test_shadow_benchmark_summary.py -q`

Expected: FAIL，统计工具不存在。

**Step 3: 实现最小基准脚本**

脚本只启动：现有 FAST-LIO2（或回放其输出）、SCAN 影子链路、指标采集和 test initial path。PCT 仍离线运行，注册探针单独计时，不把一次性全局任务算进 SCAN 稳态资源。

**Step 4: 连续运行三次代表性回放**

Run:

```bash
for run_id in 1 2 3; do
  bash scripts/3d_nav/run_shadow_benchmark.sh \
    --bag artifacts/3d_nav_feasibility/bags/b_scenario_01 \
    --run-id "$run_id"
done
python3 scripts/3d_nav/summarize_shadow_benchmark.py \
  artifacts/3d_nav_feasibility/benchmark
```

Expected: 三次 exit 0；无 OOM/backlog；规划延迟 p95 `<= 200 ms`。不满足时输出实际值并标记闸门失败。

**Step 5: 验证并提交**

```bash
python3 -m pytest test/test_shadow_benchmark_summary.py -q
git add scripts/3d_nav/run_shadow_benchmark.sh \
  scripts/3d_nav/summarize_shadow_benchmark.py test/test_shadow_benchmark_summary.py
git commit -m "test: benchmark foxy 3d navigation shadow stack"
```

### Task 9: 形成 GO/NO-GO 决策并冻结下一阶段契约

**Files:**
- Create: `docs/validation/2026-08-10-go2-3d-navigation-foxy-feasibility.md`
- Create: `config/3d_nav/interface_contract.yaml`
- Create: `test/test_3d_nav_interface_contract.py`
- Modify: `docs/plans/2026-08-10-go2-3d-navigation-upgrade-design.md`

**Step 1: 写失败的接口契约测试**

测试断言 YAML 明确列出每个输入/输出的 topic、type、frame、最低频率、最大 age、QoS 和 owner；至少包括 FAST-LIO2 odom、MID360 点云、D435i 深度、`initial_path`、SCAN 影子输出、定位结果和安全状态。禁止同一 TF edge 有两个 owner。

**Step 2: 运行测试并确认失败**

Run: `python3 -m pytest test/test_3d_nav_interface_contract.py -q`

Expected: FAIL，契约不存在。

**Step 3: 汇总真实证据**

验证报告逐项链接/记录：环境、精确 commit、补丁、构建结果、20 次注册结果、bag SHA-256、3 次 SCAN 回放、5 次 PCT 规划、资源/延迟统计、已知失败和许可证风险。每个闸门标记 `PASS` 或 `FAIL`，不得用“看起来正常”。

**Step 4: 作出决策**

- 全部 PASS：结论 `GO`，冻结 `interface_contract.yaml`，下一份计划才实现正式定位与规划节点；
- 只有可修复的非安全项失败：`CONDITIONAL-GO`，列出一个有期限的补救任务；
- PCT、SCAN 或资源闸门实质失败：`NO-GO`，回到设计文档比较候选替代，不继续堆适配层。

在设计文档追加“可行性结果”小节，只记录结论和报告路径，不重写已确认架构章节。

**Step 5: 全量验证**

Run:

```bash
python3 -m pytest test/test_3d_nav_*.py test/test_feasibility_bag_validator.py \
  test/test_pct_offline_contract.py test/test_shadow_benchmark_summary.py -q
colcon test --packages-select go2_registration_probe --event-handlers console_direct+
colcon test-result --verbose
git diff --check
git status --short
```

Expected: pytest 0 failures；colcon 0 failures；diff check 无输出；Git 只包含本任务预期文件和未跟踪运行 artifacts。

**Step 6: 请求代码审查并提交**

使用 `@superpowers:requesting-code-review` 审查：是否误接运动链、是否隐藏失败、是否存在未固定依赖、是否让 ROS 1 污染 Foxy 运行环境、是否把 runtime artifacts 提交进 Git。

```bash
git add config/3d_nav/interface_contract.yaml \
  test/test_3d_nav_interface_contract.py \
  docs/validation/2026-08-10-go2-3d-navigation-foxy-feasibility.md \
  docs/plans/2026-08-10-go2-3d-navigation-upgrade-design.md
git commit -m "docs: record foxy 3d navigation feasibility gate"
```

## 本计划之后

仅在结论为 `GO` 时编写下一份实施计划，范围依次为：

1. 全局定位状态机与平滑 `map -> odom`；
2. PCT ROS 2 在线服务和地图版本绑定；
3. SCAN 正式局部路线接口、D435i 质量门控与 Go2 包络；
4. 路径监督、模式管理、独立安全监督；
5. B 阶段低速闭环和实景验收；
6. B 稳定后集中迁移 Humble；
7. 另立 C 阶段规则楼梯计划。

这能把当前最大的不确定性限制在可丢弃的探针和薄适配层中，避免在 PCT/SCAN 尚未通过 Foxy 与 Jetson 实测前建设完整导航框架。
