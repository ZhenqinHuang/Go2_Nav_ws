# Go2 Navigation and Web Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce one clean ROS 2 project that integrates the proven FAST-LIO2/Nav2 pipeline, the formal Web console, and the external-to-internal UDP safety gateway without changing the normal hardware control boundary.

**Architecture:** Keep existing ROS packages and working algorithms, add the robot's newer gateway and Web console as first-class source packages, and centralize only stable entry points, readiness checks, map activation, and shared control status. Motion fails closed through a latched emergency-stop state, fresh ACK/localization checks, and mutually exclusive UDP/direct-DDS backends.

**Tech Stack:** ROS 2 Humble, Python 3/pytest, C++/CMake, Bash/systemd, React 19/Vite, aiohttp, Nav2, FAST-LIO2, Livox ROS driver, YAML/JSON, UDP.

---

## Execution constraints

- Preserve all pre-existing dirty worktree changes.
- Do not send non-zero velocity or posture commands during development verification.
- Use `apply_patch` for hand edits.
- Add a failing test before each behavior change.
- Import the exact deployed Web/gateway sources before modifying them; do not rebuild them from memory.
- Keep DWB as default and RPP as an optional controller profile.
- Keep PTP available, but do not make PTP lock a hard dependency for navigation.

### Task 1: Freeze the current baseline and contracts

**Files:**
- Create: `docs/architecture.md`
- Create: `docs/deployment.md`
- Create: `docs/operations.md`
- Create: `docs/troubleshooting.md`
- Create: `docs/mapping.md`
- Modify: `README.md`
- Create: `test/interface/test_project_layout.py`

**Steps:**

1. Record the current local dirty files and robot deployment file hashes without modifying either source.
2. Write a failing layout test for the required top-level packages, canonical maps, entry scripts, and documentation.
3. Add concise operator documentation derived from the approved design.
4. Update the root README to describe the canonical pipeline and link to the detailed documents.
5. Run the layout test and keep failures that belong to later tasks visible.

### Task 2: Import the formal deployed Web and gateway sources

**Files:**
- Create: `src/Go2_web_console/**`
- Create: `src/Go2_control_gateway/**`
- Modify: `.gitignore`
- Create: `docs/deployment-source-manifest.yaml`

**Steps:**

1. Read the remote package manifests and exclude build/install/log, caches, generated frontend bundles, secrets, and backup files.
2. Copy `/home/nvidia/go2_web_console/src/go2-web-console` into `src/Go2_web_console`.
3. Copy the deployed external sender and internal gateway sources into `src/Go2_control_gateway`, preserving their original package boundaries.
4. Record source host paths, copy date, and hashes in the source manifest.
5. Verify package manifests, imports, and executable bits; do not deploy the copied version yet.

### Task 3: Specify and implement the gateway safety contract

**Files:**
- Modify: `src/Go2_control_gateway/**/protocol*`
- Modify: `src/Go2_control_gateway/**/sender_core*`
- Modify: `src/Go2_control_gateway/**/gateway*`
- Modify: `src/Go2_control_gateway/**/launch/**`
- Create/Modify: corresponding Python and C++ tests

**Steps:**

1. Add failing protocol tests for `stand`, `lie`, latched `emergency_stop`, explicit reset, ACK correlation, duplicate sequence handling, and invalid commands.
2. Add failing sender tests proving a latched stop rejects new Nav2 and manual velocities until a valid reset.
3. Add failing readiness tests for missing carrier/address/route, stale ACK, stale localization, and stale gateway status.
4. Extend the smallest existing protocol representation needed for discrete commands; do not add a second transport.
5. Implement the same latch in the internal gateway and acknowledge completion of posture actions.
6. Make the external service wait/back off when `eth0` is unavailable instead of restart-looping.
7. Run gateway unit/protocol tests and a loopback zero-motion smoke test.

### Task 4: Normalize Web APIs and server-side safety

**Files:**
- Modify: `src/Go2_web_console/backend/console_core.py`
- Modify: `src/Go2_web_console/backend/console_server.py`
- Modify: `src/Go2_web_console/backend/ros_adapter.py`
- Modify: `src/Go2_web_console/backend/navigation_service.py`
- Modify: `src/Go2_web_console/backend/mapping_service.py`
- Modify: Web backend tests

**Steps:**

1. Add failing tests for the normalized `/api/control/*` routes and `{ok, code, message, data}` envelope.
2. Add failing tests proving manual and posture requests are rejected when gateway, localization, status freshness, lease, Nav2, or e-stop conditions are invalid.
3. Add failing tests proving emergency stop and navigation cancel are available to every authenticated session.
4. Add failing tests proving `recovery-stand` and direct `/api/sport/request` publication are absent.
5. Replace direct Unitree posture publication with gateway service calls for `stand` and `lie`.
6. Implement stale-state aging and the unified status schema.
7. Replace fixed initial-pose sleeps with bounded waiting for fresh localization/TF evidence.
8. Run all Web backend tests.

### Task 5: Update the existing Web UI without redesigning it

**Files:**
- Modify: `src/Go2_web_console/frontend/src/**`
- Modify/Create: frontend tests

**Steps:**

1. Add failing component/API tests for exact block reasons, latched e-stop, reset gating, stand/lie controls, and removal of recovery-stand.
2. Keep the current layout and styling while wiring the normalized API and status model.
3. Add lie confirmation, goal preview, map readiness, obstacle rejection, unknown-space warning, and unprivileged safety cancel.
4. Ensure keyboard/pointer release always emits zero and a lost connection visibly invalidates control.
5. Run frontend tests, lint, and production build.

### Task 6: Make map activation atomic and canonical

**Files:**
- Create: `maps/map_manifest.yaml`
- Create: `scripts/map_bundle.py`
- Create: `test/interface/test_map_bundle.py`
- Modify: localization and Nav2 map defaults
- Modify: mapping service tests and implementation

**Steps:**

1. Add failing tests for a complete bundle, SHA-256 mismatch, mismatched YAML image path, staging failure, and archive/promotion.
2. Implement `validate`, `create-manifest`, and `promote` operations in one dependency-light script.
3. Generate the active manifest from the canonical root map files.
4. Point ICP localization only to `maps/MID360.pcd`; point Nav2 only to `maps/MID360_map.yaml`.
5. Change Web mapping output to stage and atomically promote complete bundles.
6. Archive complete historical maps and remove only verified duplicate PCD/PGM copies from source packages.

### Task 7: Consolidate bringup and readiness checks

**Files:**
- Create: `scripts/start_mapping.sh`
- Create: `scripts/start_navigation.sh`
- Create: `scripts/check_system.sh`
- Create: `scripts/stop_all.sh`
- Modify: `src/Go2_bringup/**`
- Modify: systemd unit templates in gateway/Web/time-sync packages
- Create/Modify: shell and smoke tests

**Steps:**

1. Add failing contract tests for launch order, UDP default backend, direct-DDS mutual exclusion, and absence of fixed readiness sleeps.
2. Implement stable root entry scripts as thin wrappers around package launch files.
3. Check time validity, addresses, routes, topics, TF freshness, map manifest, Nav2 lifecycle, ACK, and e-stop state with actionable exit codes.
4. Keep perception/Web read-only startup possible when the control network is down, but block motion readiness.
5. Replace the obsolete Vite-5173 Web launcher with the formal console systemd entry point.
6. Keep PTP scripts/configuration and ensure ordinary NTP time validity precedes log- and map-producing services.

### Task 8: Retain and verify Nav2 profiles

**Files:**
- Modify: `src/Go2_nav2/config/**`
- Modify: `src/Go2_nav2/launch/nav2_bringup.launch.py`
- Modify: `src/Go2_nav2/package.xml`
- Create: `test/interface/test_nav2_profiles.py`

**Steps:**

1. Add failing tests for DWB default, RPP optional selection, common topics/frames, and one map_server owner.
2. Remove accidental configuration duplication while preserving both profiles.
3. Validate waypoint follower, behavior tree, costmap, footprint, speed, and controller parameter consistency.
4. Run YAML parsing and launch-description smoke tests in the ROS 2 environment.

### Task 9: Clean the repository conservatively

**Files:**
- Remove/archive only confirmed unreferenced temporary directories, screenshots, backup files, and duplicate maps
- Modify: `.gitignore`
- Modify: documentation references

**Steps:**

1. Build a reference report with `rg` before each removal set.
2. Remove `.codex-*`, `.inspection`, RViz trial screenshots, source backup files, generated build products, and malformed temporary known-hosts files only when unreferenced.
3. Preserve user-authored plans, tests, and all unknown dirty changes.
4. Run the full reference and project-layout tests after cleanup.

### Task 10: Verification and deployment handoff

**Files:**
- Create: `docs/verification-report-2026-08-10.md`
- Modify: `docs/deployment.md`

**Steps:**

1. Run Python tests, gateway C++ tests, frontend tests/lint/build, shell checks, YAML validation, map validation, and ROS package build where toolchains are available.
2. Record every command, result, and environment limitation in the verification report.
3. Copy the integrated sources to a versioned staging directory on the Jetson; do not replace active systemd services yet.
4. Run remote zero-motion smoke checks and verify Web HTTP/status endpoints.
5. Provide exact service cutover and rollback commands.
6. Defer non-zero velocity and posture verification until the Go2 control network is powered and the user authorizes the physical test.
