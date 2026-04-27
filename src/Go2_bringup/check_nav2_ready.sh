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

for topic in /odom /scan /cloud_registered /cloud_registered_body /livox/lidar /livox/imu /Odometry /map_to_odom; do
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
    timeout 6s ros2 topic hz "${topic}" > "${tmpfile}" 2>&1 || true

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
check_hz /cloud_registered       8   "/cloud_registered (world 帧，ICP 定位输入)"
check_hz /cloud_registered_body  8   "/cloud_registered_body (body 帧，点云滤波输入)"
check_hz /map_to_odom            0.3 "/map_to_odom (ICP 重定位，~0.5 Hz 正常)"

# ─────────────────────────────────────────────
section "3. TF 树完整性（Nav2 链路）"
# ─────────────────────────────────────────────

check_tf() {
    local src="$1"
    local dst="$2"
    local required="${3:-true}"
    local tmpfile
    tmpfile=$(mktemp)
    timeout 3s ros2 run tf2_ros tf2_echo "${src}" "${dst}" > "${tmpfile}" 2>&1 || true
    if grep -qi "translation" "${tmpfile}"; then
        pass "TF 可达: ${src} → ${dst}"
    else
        if [[ "${required}" == "true" ]]; then
            fail "TF 不可达: ${src} → ${dst}"
        else
            warn "TF 不可达: ${src} → ${dst}（可选）"
        fi
    fi
    rm -f "${tmpfile}"
}

# Nav2 核心 TF 链
check_tf odom      base_link  true
check_tf map       odom       true
check_tf map       base_link  true   # 完整链路验证

# ─────────────────────────────────────────────
section "4. 时间戳一致性"
# ─────────────────────────────────────────────

check_stamp_age() {
    local topic="$1"
    local label="$2"
    local max_age_s="${3:-1.0}"

    if ! echo "${TOPIC_LIST}" | grep -Fxq "${topic}"; then
        warn "${label} 话题不存在，跳过时间戳检查"
        return
    fi

    local tmpfile
    tmpfile=$(mktemp)
    timeout 3s ros2 topic echo --once "${topic}" > "${tmpfile}" 2>&1 || true

    local sec nsec
    sec=$(grep -A2 "stamp:" "${tmpfile}" | grep "sec:" | head -1 | awk '{print $2}' | tr -d '\r')
    nsec=$(grep -A2 "stamp:" "${tmpfile}" | grep "nanosec:" | head -1 | awk '{print $2}' | tr -d '\r')
    rm -f "${tmpfile}"

    if [[ -z "${sec}" ]]; then
        warn "${label} 无法解析时间戳"
        return
    fi

    local now_s
    now_s=$(date +%s)
    local msg_s="${sec}"
    local age
    age=$(echo "${now_s} ${msg_s}" | awk '{d=$1-$2; if(d<0)d=-d; print d}')
    local ok
    ok=$(echo "${age} ${max_age_s}" | awk '{print ($1 <= $2) ? "yes" : "no"}')

    if [[ "${ok}" == "yes" ]]; then
        pass "${label} 时间戳新鲜（age ≈ ${age}s，要求 ≤ ${max_age_s}s）"
    else
        fail "${label} 时间戳过旧（age ≈ ${age}s，要求 ≤ ${max_age_s}s）— 检查时间同步"
    fi
}

check_stamp_age /odom                  "/odom"                  1.0
check_stamp_age /cloud_registered      "/cloud_registered"      1.0
check_stamp_age /cloud_registered_body "/cloud_registered_body" 1.0
check_stamp_age /scan                  "/scan"                  1.0

# ─────────────────────────────────────────────
section "5. /scan 消息质量"
# ─────────────────────────────────────────────

if echo "${TOPIC_LIST}" | grep -Fxq "/scan"; then
    _scan_tmp=$(mktemp)
    timeout 3s ros2 topic echo /scan > "${_scan_tmp}" 2>&1 || true

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
        pass "/scan 角度覆盖 ≈ ${coverage}°"
    else
        warn "/scan 无法解析角度范围"
    fi
    rm -f "${_scan_tmp}"
else
    fail "/scan 话题不存在，跳过消息质量检查"
fi

# ─────────────────────────────────────────────
section "6. /odom 消息质量"
# ─────────────────────────────────────────────

if echo "${TOPIC_LIST}" | grep -Fxq "/odom"; then
    _odom_tmp=$(mktemp)
    timeout 3s ros2 topic echo /odom > "${_odom_tmp}" 2>&1 || true

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
section "7. 关键节点存活"
# ─────────────────────────────────────────────

for node in \
    /livox_lidar_publisher \
    /odom_tf_bridge_node \
    /map_publisher \
    /global_localization \
    /transform_fusion \
    /cloud_filter_node \
    /pointcloud_to_laserscan; do
    if echo "${NODE_LIST}" | grep -Fq "${node}"; then
        pass "节点存活: ${node}"
    else
        fail "节点缺失: ${node}"
    fi
done

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
