#!/usr/bin/env bash
# check_nav2_ready.sh
# 检查当前数据链路是否满足 Nav2 启动要求。
# 用法：bash check_nav2_ready.sh

set -uo pipefail

ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO_NAME}/setup.bash}"
GO2_NAV_WS="${GO2_NAV_WS:-${HOME}/Go2_Nav_ws}"

PASS=0
FAIL=0

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $*"; (( PASS++ )); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; (( FAIL++ )); }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
section() { echo -e "\n${BOLD}── $* ──${NC}"; }

# source ROS（忽略 unbound variable）
set +u
# shellcheck source=/dev/null
source "${ROS_SETUP}" 2>/dev/null
source "${GO2_NAV_WS}/install/setup.bash" 2>/dev/null
set -u

TOPIC_LIST="$(ros2 topic list 2>/dev/null)"
NODE_LIST="$(ros2 node list 2>/dev/null)"

# ─────────────────────────────────────────────
section "1. 必要话题存在性"
# ─────────────────────────────────────────────

for topic in /odom /scan /cloud_registered_body /livox/lidar /livox/imu; do
    if echo "${TOPIC_LIST}" | grep -Fxq "${topic}"; then
        pass "话题存在: ${topic}"
    else
        fail "话题缺失: ${topic}"
    fi
done

# ─────────────────────────────────────────────
section "2. 话题频率"
# ─────────────────────────────────────────────

check_hz() {
    local topic="$1"
    local min_hz="$2"
    local label="${3:-${topic}}"

    if ! echo "${TOPIC_LIST}" | grep -Fxq "${topic}"; then
        fail "${label} 话题不存在，跳过频率检查"
        return
    fi

    local tmpfile
    tmpfile=$(mktemp)
    # hz 输出直接写 tty，必须用 script 捕获才能重定向
    script -q -c "timeout 6s ros2 topic hz ${topic}" "${tmpfile}" >/dev/null 2>&1 || true

    local hz
    hz=$(grep "average rate" "${tmpfile}" | tail -1 | awk '{print $3}' | tr -d ':\r')
    rm -f "${tmpfile}"

    if [[ -z "${hz}" ]]; then
        fail "${label} 无法获取频率（无数据？）"
        return
    fi

    local ok
    ok=$(echo "${hz} ${min_hz}" | awk '{print ($1 >= $2) ? "yes" : "no"}')
    if [[ "${ok}" == "yes" ]]; then
        pass "${label} 频率 ≈ ${hz} Hz（要求 ≥ ${min_hz} Hz）"
    else
        fail "${label} 频率 ≈ ${hz} Hz 过低（要求 ≥ ${min_hz} Hz）"
    fi
}

check_hz /scan                   8   "/scan (LaserScan)"
check_hz /odom                   8   "/odom (Odometry)"
check_hz /cloud_registered_body  8   "/cloud_registered_body (PointCloud2)"

# ─────────────────────────────────────────────
section "3. TF 树完整性（Nav2 链路）"
# ─────────────────────────────────────────────

check_tf() {
    local src="$1"
    local dst="$2"
    local tmpfile
    tmpfile=$(mktemp)
    timeout 3s ros2 run tf2_ros tf2_echo "${src}" "${dst}" > "${tmpfile}" 2>&1 || true
    if grep -qi "translation" "${tmpfile}"; then
        pass "TF 可达: ${src} → ${dst}"
    else
        fail "TF 不可达: ${src} → ${dst}"
    fi
    rm -f "${tmpfile}"
}

# Nav2 最低要求：odom → base_link
check_tf odom base_link

# hdl_localization 启动后才有 map → odom，未启动时仅 warn
_tf_tmp=$(mktemp)
timeout 3s ros2 run tf2_ros tf2_echo map odom > "${_tf_tmp}" 2>&1 || true
if grep -qi "translation" "${_tf_tmp}"; then
    pass "TF 可达: map → odom（hdl_localization 已运行）"
else
    warn "TF 不可达: map → odom（hdl_localization 未启动，导航前需启动）"
fi
rm -f "${_tf_tmp}"

# FAST-LIO2 独立树
check_tf camera_init body

# ─────────────────────────────────────────────
section "4. /scan 消息质量"
# ─────────────────────────────────────────────

if echo "${TOPIC_LIST}" | grep -Fxq "/scan"; then
    _scan_tmp=$(mktemp)
    script -q -c "timeout 3s ros2 topic echo /scan" "${_scan_tmp}" >/dev/null 2>&1 || true

    # frame_id 格式: "  frame_id: base_link"
    frame=$(grep "frame_id:" "${_scan_tmp}" | head -1 | awk '{print $2}' | tr -d '\r')
    if [[ "${frame}" == "base_link" ]]; then
        pass "/scan frame_id = base_link"
    else
        fail "/scan frame_id = '${frame}'（Nav2 期望 base_link）"
    fi

    amin=$(grep "^angle_min:" "${_scan_tmp}" | head -1 | awk '{print $2}' | tr -d '\r')
    amax=$(grep "^angle_max:" "${_scan_tmp}" | head -1 | awk '{print $2}' | tr -d '\r')
    if [[ -n "${amin}" && -n "${amax}" ]]; then
        coverage=$(echo "${amin} ${amax}" | awk '{printf "%.1f", ($2-$1)*180/3.14159}')
        pass "/scan 角度覆盖 ≈ ${coverage}°（angle_min=${amin}, angle_max=${amax}）"
    else
        warn "/scan 无法解析角度范围"
    fi

    ranges_len=$(grep -c "^- " "${_scan_tmp}" || true)
    if (( ranges_len > 10 )); then
        pass "/scan ranges 有效点数 ≈ ${ranges_len}"
    else
        fail "/scan ranges 点数过少（${ranges_len}），点云过滤可能过严"
    fi
    rm -f "${_scan_tmp}"
else
    fail "/scan 话题不存在，跳过消息质量检查"
fi

# ─────────────────────────────────────────────
section "5. /odom 消息质量"
# ─────────────────────────────────────────────

if echo "${TOPIC_LIST}" | grep -Fxq "/odom"; then
    _odom_tmp=$(mktemp)
    script -q -c "timeout 3s ros2 topic echo /odom" "${_odom_tmp}" >/dev/null 2>&1 || true

    # 格式: "  frame_id: odom" / "child_frame_id: base_link"
    odom_frame=$(grep "frame_id:" "${_odom_tmp}" | head -1 | awk '{print $2}' | tr -d '\r')
    child_frame=$(grep "child_frame_id:" "${_odom_tmp}" | head -1 | awk '{print $2}' | tr -d '\r')

    if [[ "${odom_frame}" == "odom" ]]; then
        pass "/odom header.frame_id = odom"
    else
        fail "/odom header.frame_id = '${odom_frame}'（期望 odom）"
    fi

    if [[ "${child_frame}" == "base_link" ]]; then
        pass "/odom child_frame_id = base_link"
    else
        fail "/odom child_frame_id = '${child_frame}'（期望 base_link）"
    fi

    # 协方差：取第一个非零值判断
    cov_nonzero=$(grep -A40 "covariance:" "${_odom_tmp}" | grep -v "covariance:" \
        | awk '{print $2}' | tr -d '\r' | awk 'BEGIN{f=0} $1+0!=0{f=1} END{print f}')
    if [[ "${cov_nonzero}" == "1" ]]; then
        pass "/odom 协方差已填充（非全零）"
    else
        warn "/odom 协方差全零，Nav2 EKF 精度可能受影响"
    fi
    rm -f "${_odom_tmp}"
else
    fail "/odom 话题不存在，跳过消息质量检查"
fi

# ─────────────────────────────────────────────
section "6. 关键节点存活"
# ─────────────────────────────────────────────

for node in \
    /livox_lidar_publisher \
    /odom_tf_bridge_node \
    /cloud_filter_node \
    /pointcloud_to_laserscan; do
    if echo "${NODE_LIST}" | grep -Fq "${node}"; then
        pass "节点存活: ${node}"
    else
        fail "节点缺失: ${node}"
    fi
done

# fastlio 节点名不固定，模糊匹配
if echo "${NODE_LIST}" | grep -q "laser_mapping\|fastlio\|fast_lio"; then
    pass "节点存活: FAST-LIO2 (laser_mapping)"
else
    fail "节点缺失: FAST-LIO2"
fi

# ─────────────────────────────────────────────
section "结果汇总"
# ─────────────────────────────────────────────

echo ""
echo -e "  ${GREEN}PASS: ${PASS}${NC}   ${RED}FAIL: ${FAIL}${NC}"
echo ""

if (( FAIL == 0 )); then
    echo -e "${GREEN}${BOLD}✓ 数据链路满足 Nav2 启动要求${NC}"
    exit 0
else
    echo -e "${RED}${BOLD}✗ 存在 ${FAIL} 项问题，请修复后再启动 Nav2${NC}"
    exit 1
fi
