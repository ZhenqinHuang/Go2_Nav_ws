# MID360 Jetson Preparation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prepare the Ubuntu 20.04 / ROS 2 Foxy Jetson for a directly connected Livox MID360 by installing pinned SDK, driver, and FAST-LIO2 sources and documenting a reproducible, reversible workflow.

**Architecture:** Keep Livox and FAST-LIO2 in separate ROS 2 overlay workspaces under `/home/nvidia`, with `Go2_Nav_ws` as the final overlay. Configure `eth0` as an isolated `192.168.1.5/24` sensor network with no default route, while `wlan0` remains the management and internet interface.

**Tech Stack:** Ubuntu 20.04, ARM64, ROS 2 Foxy, NetworkManager, Livox-SDK2, livox_ros_driver2, Ericsii/FAST_LIO_ROS2, Bash, CMake, colcon, Git.

---

### Task 1: Capture the pre-change Jetson state

**Files:**
- Create on Jetson: `/home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange/`
- Create on Jetson: `/home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange/system-inventory.txt`
- Create on Jetson: `/home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange/bashrc`
- Create on Jetson: `/home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange/networkmanager-connections.txt`

**Step 1: Verify the backup target**

Run:

```bash
readlink -f /home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723
```

Expected: the resolved path remains under `/home/nvidia/Go2_Nav_ws/.codex_backups`.

**Step 2: Create the backup directory and copy shell configuration**

Run:

```bash
mkdir -p /home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange
cp -a /home/nvidia/.bashrc \
  /home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange/bashrc
```

Expected: copied file exists and has a nonzero size.

**Step 3: Record system, package, Git, ROS, network, and disk state**

Record:

```bash
uname -a
lsb_release -a
dpkg --print-architecture
cmake --version
gcc --version
git --version
df -h /
ip -br addr
ip route
nmcli connection show
ros2 pkg list
```

Expected: one timestamped inventory file that can be compared after installation.

**Step 4: Verify backup integrity**

Run:

```bash
test -s /home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange/bashrc
test -s /home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange/system-inventory.txt
```

Expected: both commands exit `0`.

### Task 2: Add reproducible configuration and helper scripts

**Files:**
- Create: `scripts/mid360/install_mid360_stack.sh`
- Create: `scripts/mid360/configure_mid360_network.sh`
- Create: `scripts/mid360/config/MID360_config.json`
- Create: `scripts/mid360/config/mid360.yaml`
- Create: `scripts/mid360/verify_mid360_preparation.sh`

**Step 1: Write syntax and configuration smoke tests**

Run before creating the files:

```bash
bash -n scripts/mid360/install_mid360_stack.sh
```

Expected: fail because the file does not yet exist.

**Step 2: Implement the installer**

The installer must:

1. require Ubuntu 20.04, ARM64 and `/opt/ros/foxy/setup.bash`;
2. install only required apt dependencies;
3. clone or reuse clean repositories;
4. checkout and verify:
   - Livox-SDK2 `f5d9375f84efe2b15bc0a052d3e18482ed13adf4`;
   - livox_ros_driver2 `13eb05e4e6dd7a765b934d0c5fd6236676a57b49`;
   - FAST_LIO_ROS2 `2fffc570a25d0df172720bac034fbdb6a13d2162`;
5. initialize FAST-LIO2 submodules;
6. install Livox-SDK2 to `/usr/local`;
7. build `~/ws_Livox` using `./build.sh ROS2`;
8. source the Livox overlay and build `~/ws_fastlio2` with colcon;
9. copy the repository-owned MID360 templates before their corresponding builds;
10. refuse to overwrite dirty third-party repositories.

**Step 3: Implement the network helper**

The helper must idempotently create or update `mid360-direct` with:

```text
interface              eth0
IPv4 address           192.168.1.5/24
IPv4 gateway           empty
IPv4 DNS               empty
ipv4.never-default     yes
autoconnect            yes
autoconnect priority   100
```

It must not change `wlan0`, and it must not fail just because no Ethernet carrier is present.

**Step 4: Add configuration templates**

`MID360_config.json` must use host IP `192.168.1.5`, official placeholder LiDAR IP `192.168.1.12`, and official MID360 UDP ports.

`mid360.yaml` must use `/livox/lidar`, `/livox/imu`, Livox type `1`, 10 Hz, `time_sync_en: false`, and save PCD data under `/home/nvidia/Go2_Nav_ws/maps`.

**Step 5: Implement the verification helper**

The helper must check:

- pinned repository revisions;
- installed Livox SDK library/header;
- ROS package visibility;
- expected launch files;
- NetworkManager profile and default route;
- configuration JSON/YAML parseability;
- current lack or presence of Ethernet carrier without treating missing hardware as a software failure.

**Step 6: Run local static tests**

Run:

```bash
bash -n scripts/mid360/install_mid360_stack.sh
bash -n scripts/mid360/configure_mid360_network.sh
bash -n scripts/mid360/verify_mid360_preparation.sh
python -m json.tool scripts/mid360/config/MID360_config.json
git diff --check
```

Expected: all commands exit `0`.

**Step 7: Commit**

```bash
git add scripts/mid360
git commit -m "feat: add reproducible MID360 preparation tools"
```

### Task 3: Repair Go2 integration assumptions

**Files:**
- Modify: `src/Go2_bringup/go2_nav_start.sh`
- Modify: `src/Go2_bringup/time_sync_start.sh`
- Modify: `src/Go2_time_sync/config/ptp_sync.yaml`
- Modify: `src/Go2_Slam/README.md`

**Step 1: Add a regression search**

Run:

```bash
grep -RInE '/home/unitree/ws_Livox|/home/unitree/ws_fastlio2|192\.168\.123\.' \
  src/Go2_bringup src/Go2_time_sync src/Go2_Slam
```

Expected before the fix: matches in comments and `time_sync_start.sh`.

**Step 2: Apply minimal path and subnet fixes**

Use `${HOME}/ws_Livox` and `${HOME}/ws_fastlio2` as defaults. Make LiDAR IP, host IP and interface overridable environment variables with `192.168.1.12`, `192.168.1.5`, and `eth0` as defaults. Keep PTP disabled as documented until hardware validation.

Update the time-sync YAML so it cannot silently restore the obsolete
`192.168.123.x` subnet. Correct the FAST-LIO configuration documentation so
MID360 `lidar_type` is numeric `1`.

**Step 3: Run shell syntax and regression checks**

Run:

```bash
bash -n src/Go2_bringup/go2_nav_start.sh
bash -n src/Go2_bringup/time_sync_start.sh
! grep -RInE '/home/unitree/ws_Livox|/home/unitree/ws_fastlio2|192\.168\.123\.' \
  src/Go2_bringup src/Go2_time_sync src/Go2_Slam
git diff --check
```

Expected: all commands exit `0`.

**Step 4: Commit**

```bash
git add src/Go2_bringup/go2_nav_start.sh \
  src/Go2_bringup/time_sync_start.sh \
  src/Go2_time_sync/config/ptp_sync.yaml \
  src/Go2_Slam/README.md
git commit -m "fix: align Go2 bringup with Jetson MID360 workspaces"
```

### Task 4: Deploy the preparation tools and take backups

**Files:**
- Copy to Jetson: `/home/nvidia/Go2_Nav_ws/scripts/mid360/`
- Copy to Jetson: `/home/nvidia/Go2_Nav_ws/src/Go2_bringup/`
- Copy to Jetson: `/home/nvidia/Go2_Nav_ws/src/Go2_Slam/README.md`

**Step 1: Verify the remote target**

Run:

```bash
readlink -f /home/nvidia/Go2_Nav_ws
test -d /home/nvidia/Go2_Nav_ws/src
```

Expected: target is exactly `/home/nvidia/Go2_Nav_ws`.

**Step 2: Perform Task 1 backup**

Expected: the backup integrity checks pass before any remote file or system change.

**Step 3: Transfer repository-owned files**

Use SFTP with exact paths and preserve executable mode for shell scripts.

**Step 4: Verify transferred hashes**

Run SHA-256 on local and remote files.

Expected: every transferred file has the same hash.

### Task 5: Install pinned SDK, driver, and FAST-LIO2

**Files:**
- Create on Jetson: `/home/nvidia/Livox-SDK2`
- Create on Jetson: `/home/nvidia/ws_Livox`
- Create on Jetson: `/home/nvidia/ws_fastlio2`
- Install system files under: `/usr/local/include`, `/usr/local/lib`

**Step 1: Run the installer with the supplied sudo password**

Run:

```bash
cd /home/nvidia/Go2_Nav_ws
bash scripts/mid360/install_mid360_stack.sh
```

Expected: apt installation, three pinned checkouts, SDK install, driver build, and FAST-LIO2 build all exit `0`.

**Step 2: Verify source revisions**

Run:

```bash
git -C ~/Livox-SDK2 rev-parse HEAD
git -C ~/ws_Livox/src/livox_ros_driver2 rev-parse HEAD
git -C ~/ws_fastlio2/src/FAST_LIO_ROS2 rev-parse HEAD
git -C ~/ws_fastlio2/src/FAST_LIO_ROS2 submodule status --recursive
```

Expected: the three expected commit IDs and initialized submodules without a leading `-`.

**Step 3: Verify SDK installation**

Run:

```bash
ldconfig -p | grep livox
find /usr/local/include -maxdepth 2 -iname 'livox_lidar*'
```

Expected: at least one Livox SDK library and installed headers.

**Step 4: Verify ROS packages**

Run:

```bash
source /opt/ros/foxy/setup.bash
source ~/ws_Livox/install/setup.bash
source ~/ws_fastlio2/install/setup.bash
ros2 pkg prefix livox_ros_driver2
ros2 pkg prefix fast_lio
```

Expected: prefixes under `~/ws_Livox/install` and `~/ws_fastlio2/install`.

### Task 6: Configure the isolated MID360 Ethernet profile

**Files:**
- Create through NetworkManager: `mid360-direct`

**Step 1: Run the network helper**

Run:

```bash
sudo bash /home/nvidia/Go2_Nav_ws/scripts/mid360/configure_mid360_network.sh
```

Expected: `mid360-direct` exists even when `eth0` has no carrier.

**Step 2: Verify the profile**

Run:

```bash
nmcli -f connection.id,connection.interface-name,connection.autoconnect,connection.autoconnect-priority,ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.never-default connection show mid360-direct
```

Expected: `eth0`, `192.168.1.5/24`, no gateway, `never-default=yes`, priority `100`.

**Step 3: Verify management connectivity is unchanged**

Run:

```bash
ip route show default
ip -br addr show wlan0
```

Expected: default route remains through `wlan0` and the SSH session remains connected.

### Task 7: Add guarded shell overlay loading

**Files:**
- Modify on Jetson: `/home/nvidia/.bashrc`

**Step 1: Insert guarded Livox and FAST-LIO source lines**

Place them after the Unitree overlay and before the Go2 overlay:

```bash
if [ -f /home/nvidia/ws_Livox/install/setup.bash ]; then
  source /home/nvidia/ws_Livox/install/setup.bash
fi
if [ -f /home/nvidia/ws_fastlio2/install/setup.bash ]; then
  source /home/nvidia/ws_fastlio2/install/setup.bash
fi
```

Do not duplicate the block if the installer is rerun.

**Step 2: Test a clean interactive shell**

Run:

```bash
bash -ic 'ros2 pkg prefix livox_ros_driver2; ros2 pkg prefix fast_lio'
```

Expected: both package prefixes resolve without shell startup errors.

### Task 8: Perform offline launch and workspace verification

**Files:**
- Build: `/home/nvidia/Go2_Nav_ws`
- Log: `/home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/postchange/verification.log`

**Step 1: Validate configuration files**

Run:

```bash
python3 -m json.tool ~/ws_Livox/src/livox_ros_driver2/config/MID360_config.json
python3 -c "import yaml; yaml.safe_load(open('/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml'))"
```

Expected: both exit `0`.

**Step 2: Validate launch arguments**

Run:

```bash
source /opt/ros/foxy/setup.bash
source ~/ws_Livox/install/setup.bash
source ~/ws_fastlio2/install/setup.bash
ros2 launch livox_ros_driver2 msg_MID360_launch.py --show-args
ros2 launch fast_lio mapping.launch.py --show-args
```

Expected: launch descriptions load without missing package, shared-library, or Python import errors.

**Step 3: Run bounded no-hardware launch smoke tests**

Start each launch under a timeout and inspect logs. Exit `124` is acceptable only when the node stayed alive waiting for unavailable hardware. Missing shared libraries, missing packages, process crashes, and configuration parse errors are failures.

**Step 4: Rebuild the complete Go2 workspace**

Run:

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/unitree_ros2/cyclonedds_ws/install/setup.bash
source ~/ws_Livox/install/setup.bash
source ~/ws_fastlio2/install/setup.bash
cd /home/nvidia/Go2_Nav_ws
colcon build --symlink-install
colcon test
colcon test-result --verbose
```

Expected: build exits `0`; test results contain no failures.

**Step 5: Run the preparation verifier**

Run:

```bash
bash /home/nvidia/Go2_Nav_ws/scripts/mid360/verify_mid360_preparation.sh
```

Expected: all software checks pass; hardware-only checks are reported as pending.

### Task 9: Write the technical manual and actual installation record

**Files:**
- Create: `docs/MID360_Jetson_Foxy_技术手册.md`
- Create: `docs/mid360/安装记录_2026-07-23.md`
- Modify: `README.md`

**Step 1: Document reproducible setup**

Include:

- final topology;
- exact source URLs and commit IDs;
- directory layout;
- dependency installation;
- build and environment order;
- network configuration;
- configuration file fields;
- normal start commands;
- troubleshooting and rollback;
- hardware-arrival checklist;
- security note that passwords and credentials are never committed.

**Step 2: Record actual evidence and encountered problems**

For each issue, record:

```text
Symptom
Cause
Evidence
Fix
Verification
Remaining limitation
```

Record command outputs compactly, including build summaries and package prefixes, without credentials or sensitive tokens.

**Step 3: Link the manual from the root README**

Add one entry under the documentation section.

**Step 4: Verify documentation**

Run:

```bash
git diff --check
grep -RInE 'password|token|secret|nvidia/nvidia' docs scripts/mid360
```

Expected: formatting check passes and no credential is present.

**Step 5: Commit**

```bash
git add README.md docs
git commit -m "docs: add MID360 Jetson Foxy technical manual"
```

### Task 10: Final verification and GitHub backup

**Files:**
- All files changed by this plan

**Step 1: Apply @superpowers:verification-before-completion**

Run every repository and Jetson verification command fresh. Do not infer success from an earlier build.

**Step 2: Review repository scope**

Run:

```bash
git status --short --branch
git diff origin/main...HEAD --stat
git log --oneline origin/main..HEAD
```

Expected: only MID360 preparation, integration fixes, plans, and documentation are present.

**Step 3: Push the isolated branch**

```bash
git push -u origin docs/mid360-prep
```

Expected: GitHub confirms the branch update.

**Step 4: Integrate after verification**

Fast-forward or merge the verified branch into `main`, then push `main`. Record the final commit ID in the installation record.

**Step 5: Verify GitHub state**

Run:

```bash
git ls-remote origin refs/heads/main refs/heads/docs/mid360-prep
```

Expected: remote references match the local verified commits.
