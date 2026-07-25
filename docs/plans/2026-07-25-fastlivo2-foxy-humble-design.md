# FAST-LIVO2 Foxy Deployment with Humble Migration Design

## Goal

Deploy FAST-LIVO2 for a Livox MID-360S and Intel RealSense D435i on the
Jetson Orin NX 16GB while preserving the existing FAST-LIO2 and Nav2 system.
The deployment must run on Ubuntu 20.04 with ROS 2 Foxy today and keep the
sensor configuration, calibration, launch interface, and validation workflow
portable to ROS 2 Humble later.

## Existing System

- Jetson Orin NX 16GB, Jetson Linux R35.6.4, Ubuntu 20.04, ROS 2 Foxy.
- Current power mode is 25 W.
- Existing workspaces:
  - `/home/nvidia/ws_Livox`
  - `/home/nvidia/ws_fastlio2`
  - `/home/nvidia/Go2_Nav_ws`
- Existing Livox-SDK2 and `livox_ros_driver2` publish MID-360S custom point
  clouds and IMU data at 10 Hz.
- Jetson Ethernet is `192.168.1.5/24`; MID-360S is `192.168.1.158`.
- The D435i is connected over USB 3 and enumerates as `8086:0b3a`.
- The existing Ethernet adapter has software timestamp support but no PTP
  hardware clock.
- Existing FAST-LIO2 and Livox repositories contain local changes. They are
  reference material and must not be modified or reset.

## Selected Approach

Create `/home/nvidia/fastlivo2_ws` as a completely separate colcon workspace.
Use a pinned ROS 2 Humble FAST-LIVO2 port as the upstream source and keep Foxy
adaptations in a small, auditable compatibility layer. Keep sensor parameters
and calibration data outside the upstream algorithm repository.

Do not install ROS 1, do not upgrade the current root filesystem, and do not
introduce Docker for the initial Foxy deployment.

When Humble migration is required, prepare a separate JetPack 6 / Ubuntu 22.04
system image or NVMe installation. The current JetPack 5 / Foxy installation
remains a bootable rollback target.

## Isolation Rules

The deployment must not:

- edit `/home/nvidia/ws_Livox`;
- edit `/home/nvidia/ws_fastlio2`;
- edit `/home/nvidia/Go2_Nav_ws`;
- modify the user's `.bashrc`;
- replace existing systemd services;
- kill existing ROS nodes;
- write maps into the existing navigation workspace;
- run a second Livox driver while the current driver is active.

The new startup command must perform a preflight check. If an existing Livox,
FAST-LIO, FAST-LIVO2, or Nav2 process is active, it must fail with a clear
message instead of stopping or replacing that process.

New nodes and outputs use the `/fastlivo2` namespace. Compatibility remaps to
the existing navigation topic names are optional and are only enabled when the
old mapping/localization stack is stopped.

## Workspace Layout

```text
/home/nvidia/fastlivo2_ws/
├── src/
│   ├── fast_livo2/
│   ├── rpg_vikit/
│   └── fastlivo2_bringup/
├── compat/
│   └── foxy/
├── config/
│   ├── common/
│   ├── foxy/
│   └── humble/
├── manifests/
│   ├── foxy.repos
│   └── humble.repos
├── deps/
├── maps/
├── logs/
└── scripts/
```

`config/common` owns the MID-360S address, topic names, D435i stream profile,
camera intrinsics, LiDAR-camera temporal offset, and LiDAR-camera extrinsics.
No hardware calibration value is stored only in a distribution-specific file.

## Dependency Strategy

- Reuse the installed Livox-SDK2 library and the existing Livox driver at
  runtime without modifying their source.
- Pin every cloned repository to a commit and record the commit in the
  workspace manifest.
- Build Sophus and Vikit inside the new workspace or a private dependency
  prefix. Do not install them into `/usr/local` unless private-prefix linking is
  proven impossible.
- Build a Foxy-compatible RealSense ROS 2 wrapper in the new workspace.
- Build librealsense with the RSUSB/libuvc backend when required by the Jetson
  kernel. Do not patch or replace the Jetson kernel for this deployment.
- Keep Foxy-specific CMake and API changes separate from common sensor
  configuration so they can be dropped on Humble.

## Sensor Data Flow

```text
MID-360S
  ├── /livox/lidar  (livox_ros_driver2/CustomMsg)
  └── /livox/imu    (sensor_msgs/Imu)
                         │
                         ├──────────────┐
                         │              │
D435i RGB                │              ▼
  └── color/image_raw ───┴──────> FAST-LIVO2
                                        │
                                        ├── /fastlivo2/odometry
                                        ├── /fastlivo2/cloud_registered
                                        ├── /fastlivo2/path
                                        └── maps/*.pcd
```

The D435i depth, infrared, accelerometer, and gyroscope streams are disabled
for the initial FAST-LIVO2 deployment. FAST-LIVO2 receives RGB images from the
D435i and inertial measurements from the MID-360S.

Start with D435i RGB at 640x480 and 15 Hz. Increase to 30 Hz only after
processing latency, dropped frames, CPU load, temperature, and memory use pass
the acceptance checks.

## Time Architecture

Jetson `CLOCK_REALTIME` is the common time base.

1. The Jetson system clock is disciplined by NTP when network access is
   available.
2. `ptp4l` runs as a software-timestamp PTP master on `eth0`.
3. MID-360S is the PTP slave and timestamps LiDAR and IMU samples against that
   master.
4. The D435i does not participate in IEEE 1588 PTP. RealSense Global Time
   converts the D435i device clock into the Jetson system-clock domain.
5. FAST-LIVO2 consumes messages only after their ROS timestamps are in the
   same Jetson clock domain.

The new workspace references the existing PTP implementation but does not copy
its service into a second concurrently managed daemon. It provides read-only
preflight and validation commands for:

- PTP process state;
- MID-360S PTP packet exchange;
- Livox `timebase` and time type;
- RealSense timestamp domain and Global Time state;
- camera-to-LiDAR timestamp delta distribution;
- backward timestamps and discontinuities.

PTP master process state alone is not proof that the MID-360S is synchronized.
The validation must observe PTP traffic or verified Livox timestamps.

## Calibration

Three separate calibrations are tracked:

1. MID-360S LiDAR-to-IMU extrinsics.
2. D435i RGB camera intrinsics for the exact stream profile.
3. MID-360S-to-D435i RGB camera extrinsics and residual temporal offset.

Existing FAST-LIO2 LiDAR-to-IMU values are reference values only. FAST-LIVO2
visual fusion remains disabled until valid camera intrinsics and
LiDAR-to-camera extrinsics are installed.

The validation sequence is:

1. verify MID-360S and IMU topics;
2. verify FAST-LIVO2 in LiDAR-inertial mode;
3. verify D435i RGB and camera information;
4. measure timestamp deltas;
5. install calibrated LiDAR-camera extrinsics;
6. enable visual fusion;
7. validate odometry and map quality.

## Performance Plan

FAST-LIVO2 is primarily CPU-bound on this platform. The initial runtime uses:

- Jetson 25 W mode;
- MID-360S at 10 Hz;
- D435i RGB 640x480 at 15 Hz;
- no depth or infrared streams;
- no RViz on the Jetson;
- bounded map output under the new workspace.

Record CPU utilization, resident memory, per-frame processing time, sensor
rates, dropped frames, and thermal throttling during a minimum 10-minute test.
The initial real-time requirement is a sustained per-LiDAR-frame processing
time below 100 ms without unbounded queue growth.

## Error Handling

- Preflight failure stops only the new launcher.
- Missing sensors, duplicate drivers, incompatible topics, and invalid
  calibration produce explicit errors.
- The startup script never kills another process automatically.
- A build failure leaves the existing workspaces untouched.
- Output directories are created only under `/home/nvidia/fastlivo2_ws`.
- Source revisions and build logs are recorded for reproduction.

## Acceptance Criteria

Deployment is accepted when:

- all new files live under `/home/nvidia/fastlivo2_ws`;
- the existing three workspaces and services are unchanged;
- the Foxy workspace builds from a clean build directory;
- D435i and MID-360S are detected;
- Livox custom point cloud and IMU topics have stable rates;
- D435i RGB and camera information have stable rates;
- timestamp-domain checks pass with no backward jumps;
- FAST-LIVO2 starts in LiDAR-inertial mode and publishes odometry;
- visual mode starts after calibration values are present;
- a PCD map is written under the new workspace;
- the new stack stops cleanly;
- the original FAST-LIO2/Nav2 startup still passes its existing readiness
  checks after the new stack is stopped;
- repository manifests and build instructions cover both Foxy and Humble.

## Out of Scope for Initial Deployment

- Reflashing the Jetson to JetPack 6.
- Replacing the existing navigation stack.
- Running old FAST-LIO2 and new FAST-LIVO2 simultaneously.
- Treating D435i depth data as a FAST-LIVO2 input.
- Claiming final LIVO accuracy before LiDAR-camera calibration and live motion
  testing.
