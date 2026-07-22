#!/usr/bin/env bash
# Install the pinned MID360 software stack on the Go2 Jetson.
#
# This script intentionally keeps third-party components in independent
# workspaces expected by Go2_Nav_ws:
#   ~/Livox-SDK2
#   ~/ws_Livox
#   ~/ws_fastlio2

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GO2_NAV_WS="${GO2_NAV_WS:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO_NAME}/setup.bash}"
LIVOX_SDK_DIR="${LIVOX_SDK_DIR:-${HOME}/Livox-SDK2}"
LIVOX_WS="${LIVOX_WS:-${HOME}/ws_Livox}"
FASTLIO_WS="${FASTLIO_WS:-${HOME}/ws_fastlio2}"
BACKUP_ROOT="${BACKUP_ROOT:-${GO2_NAV_WS}/.codex_backups/mid360-prep-20260723}"

LIVOX_SDK_URL="https://github.com/Livox-SDK/Livox-SDK2.git"
LIVOX_SDK_COMMIT="f5d9375f84efe2b15bc0a052d3e18482ed13adf4"
LIVOX_DRIVER_URL="https://github.com/Livox-SDK/livox_ros_driver2.git"
LIVOX_DRIVER_COMMIT="13eb05e4e6dd7a765b934d0c5fd6236676a57b49"
FASTLIO_URL="https://github.com/Ericsii/FAST_LIO_ROS2.git"
FASTLIO_COMMIT="2fffc570a25d0df172720bac034fbdb6a13d2162"

BUILD_JOBS="${BUILD_JOBS:-$(nproc)}"
if (( BUILD_JOBS > 6 )); then
    BUILD_JOBS=6
fi

log()  { printf '[MID360] %s\n' "$*"; }
warn() { printf '[MID360][WARN] %s\n' "$*" >&2; }
die()  { printf '[MID360][ERROR] %s\n' "$*" >&2; exit 1; }

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "缺少命令: $1"
}

source_setup() {
    local setup_file="$1"
    [[ -f "${setup_file}" ]] || die "找不到环境文件: ${setup_file}"
    set +u
    # shellcheck source=/dev/null
    source "${setup_file}"
    set -u
}

repo_status_is_allowed() {
    local repo_dir="$1"
    local allowed_paths="${2:-}"
    local line path allowed matched

    while IFS= read -r line; do
        [[ -z "${line}" ]] && continue
        path="${line:3}"
        matched=0
        for allowed in ${allowed_paths}; do
            if [[ "${path}" == "${allowed}" ]]; then
                matched=1
                break
            fi
        done
        if (( matched == 0 )); then
            return 1
        fi
    done < <(git -C "${repo_dir}" status --porcelain)
    return 0
}

prepare_repo() {
    local url="$1"
    local repo_dir="$2"
    local commit="$3"
    local branch="${4:-}"
    local allowed_path="${5:-}"
    local current

    if [[ ! -e "${repo_dir}" ]]; then
        mkdir -p "$(dirname "${repo_dir}")"
        if [[ -n "${branch}" ]]; then
            git clone --recursive --branch "${branch}" "${url}" "${repo_dir}"
        else
            git clone --recursive "${url}" "${repo_dir}"
        fi
    fi

    [[ -d "${repo_dir}/.git" ]] || die "路径已存在但不是 Git 仓库: ${repo_dir}"
    repo_status_is_allowed "${repo_dir}" "${allowed_path}" ||
        die "第三方仓库存在非托管修改，请先人工检查: ${repo_dir}"

    current="$(git -C "${repo_dir}" rev-parse HEAD)"
    if [[ "${current}" != "${commit}" ]]; then
        [[ -z "$(git -C "${repo_dir}" status --porcelain)" ]] ||
            die "仓库不是目标版本且存在修改: ${repo_dir}"
        git -C "${repo_dir}" fetch --tags origin
        if [[ -n "${branch}" ]]; then
            git -C "${repo_dir}" fetch origin "${branch}"
        fi
        git -C "${repo_dir}" checkout --detach "${commit}"
    fi

    current="$(git -C "${repo_dir}" rev-parse HEAD)"
    [[ "${current}" == "${commit}" ]] ||
        die "版本固定失败: ${repo_dir}, 当前 ${current}"
}

install_managed_config() {
    local source_file="$1"
    local repo_dir="$2"
    local relative_path="$3"
    local destination="${repo_dir}/${relative_path}"
    local backup="${BACKUP_ROOT}/vendor-defaults/${relative_path//\//__}"

    [[ -f "${source_file}" ]] || die "配置模板不存在: ${source_file}"
    [[ -f "${destination}" ]] || die "第三方默认配置不存在: ${destination}"

    if cmp -s "${source_file}" "${destination}"; then
        log "配置已是目标版本: ${destination}"
        return
    fi

    if ! git -C "${repo_dir}" diff --quiet -- "${relative_path}"; then
        die "检测到人工修改，拒绝覆盖: ${destination}"
    fi

    mkdir -p "$(dirname "${backup}")"
    if [[ ! -e "${backup}" ]]; then
        cp -a "${destination}" "${backup}"
    fi
    install -m 0644 "${source_file}" "${destination}"
    log "已安装配置: ${destination}"
}

install_managed_patch() {
    local patch_file="$1"
    local repo_dir="$2"
    local relative_path="$3"
    local source_file="${repo_dir}/${relative_path}"
    local backup="${BACKUP_ROOT}/vendor-defaults/${relative_path//\//__}"

    [[ -f "${patch_file}" ]] || die "兼容补丁不存在: ${patch_file}"
    [[ -f "${source_file}" ]] || die "补丁目标不存在: ${source_file}"

    if git -C "${repo_dir}" apply --reverse --check "${patch_file}" \
        >/dev/null 2>&1; then
        log "兼容补丁已应用: ${relative_path}"
        return
    fi

    git -C "${repo_dir}" diff --quiet -- "${relative_path}" ||
        die "检测到人工源码修改，拒绝应用补丁: ${source_file}"
    git -C "${repo_dir}" apply --check "${patch_file}" ||
        die "补丁与固定源码版本不匹配: ${patch_file}"

    mkdir -p "$(dirname "${backup}")"
    if [[ ! -e "${backup}" ]]; then
        cp -a "${source_file}" "${backup}"
    fi
    git -C "${repo_dir}" apply "${patch_file}"
    log "已应用 ROS 2 Foxy 兼容补丁: ${relative_path}"
}

main() {
    local os_id os_version arch
    os_id="$(. /etc/os-release; printf '%s' "${ID}")"
    os_version="$(. /etc/os-release; printf '%s' "${VERSION_ID}")"
    arch="$(dpkg --print-architecture)"

    [[ "${os_id}" == "ubuntu" && "${os_version}" == "20.04" ]] ||
        die "仅支持 Ubuntu 20.04，当前 ${os_id} ${os_version}"
    [[ "${arch}" == "arm64" ]] || die "仅支持 Jetson ARM64，当前 ${arch}"
    [[ -f "${ROS_SETUP}" ]] || die "未找到 ROS 2 Foxy: ${ROS_SETUP}"

    require_command git
    require_command cmake
    require_command sudo
    require_command rosdep
    sudo -v

    log "安装构建依赖"
    sudo apt-get update
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
        build-essential \
        cmake \
        git \
        libboost-all-dev \
        libeigen3-dev \
        libpcl-dev \
        python3-colcon-common-extensions \
        python3-rosdep \
        ros-foxy-pcl-conversions \
        ros-foxy-pcl-ros

    log "准备 Livox-SDK2 ${LIVOX_SDK_COMMIT}"
    prepare_repo \
        "${LIVOX_SDK_URL}" \
        "${LIVOX_SDK_DIR}" \
        "${LIVOX_SDK_COMMIT}"

    cmake -S "${LIVOX_SDK_DIR}" -B "${LIVOX_SDK_DIR}/build" \
        -DCMAKE_BUILD_TYPE=Release
    cmake --build "${LIVOX_SDK_DIR}/build" --parallel "${BUILD_JOBS}"
    sudo cmake --install "${LIVOX_SDK_DIR}/build"
    sudo ldconfig

    log "准备 livox_ros_driver2 ${LIVOX_DRIVER_COMMIT}"
    prepare_repo \
        "${LIVOX_DRIVER_URL}" \
        "${LIVOX_WS}/src/livox_ros_driver2" \
        "${LIVOX_DRIVER_COMMIT}" \
        "" \
        "config/MID360_config.json"
    install_managed_config \
        "${SCRIPT_DIR}/config/MID360_config.json" \
        "${LIVOX_WS}/src/livox_ros_driver2" \
        "config/MID360_config.json"

    source_setup "${ROS_SETUP}"
    (
        cd "${LIVOX_WS}/src/livox_ros_driver2"
        ./build.sh ROS2
    )

    log "准备 FAST_LIO_ROS2 ${FASTLIO_COMMIT}"
    prepare_repo \
        "${FASTLIO_URL}" \
        "${FASTLIO_WS}/src/FAST_LIO_ROS2" \
        "${FASTLIO_COMMIT}" \
        "ros2" \
        "config/mid360.yaml src/laserMapping.cpp"
    git -C "${FASTLIO_WS}/src/FAST_LIO_ROS2" submodule update --init --recursive
    install_managed_patch \
        "${SCRIPT_DIR}/patches/fast_lio_ros2_foxy_service_callback.patch" \
        "${FASTLIO_WS}/src/FAST_LIO_ROS2" \
        "src/laserMapping.cpp"
    install_managed_config \
        "${SCRIPT_DIR}/config/mid360.yaml" \
        "${FASTLIO_WS}/src/FAST_LIO_ROS2" \
        "config/mid360.yaml"

    source_setup "${ROS_SETUP}"
    source_setup "${LIVOX_WS}/install/setup.bash"
    rosdep install \
        --from-paths "${FASTLIO_WS}/src" \
        --ignore-src \
        --rosdistro "${ROS_DISTRO_NAME}" \
        -r -y
    (
        cd "${FASTLIO_WS}"
        colcon build --symlink-install --parallel-workers "${BUILD_JOBS}"
    )

    log "安装完成。下一步运行 configure_mid360_network.sh 和验证脚本。"
}

main "$@"
