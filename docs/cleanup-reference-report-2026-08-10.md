# Cleanup reference report — 2026-08-10

The cleanup was preceded by repository-wide `rg` and SHA-256 checks.

## Superseded bringup entry points

The following files were referenced only by the legacy bringup README, historical
plans/logs, or each other. They are superseded by the four canonical root scripts
and the formal systemd services:

- `build_map.sh`
- `check_nav2_ready.sh`
- `go2_autostart.sh`
- `go2_nav_start.sh`
- `run_nav2.sh`
- `run_robot_web.sh`
- `go2-autostart.service`

`run_keyboard_teleop.sh`, `run_web_bridge.sh`, and PTP tooling are retained as
optional features.

## Verified duplicate maps

These three PCD files were byte-identical, size `3,792,123`, SHA-256
`91a1369292036bf5f4724eb3e992ab47d45d31abe3980698f9f7c2b5e6c5db03`:

- canonical `maps/MID360.pcd` (retained);
- `src/Go2_localization/PCD/MID360_localization_filtered.pcd` (removed);
- `src/Go2_localization/fast_lio_localization_ros2/PCD/MID360.pcd` (removed).

The root-level `MID360_map.pgm` was not identical to the active map and was
therefore treated as a legacy artifact rather than a duplicate. It was removed
from the deliverable but preserved in the ignored local archive during cleanup.

Two unreferenced `.codex_backups/git-pull-20260507-1421/*.pgm` files were also
removed from the deliverable. Neither matched the canonical active PGM.

## Generated and documentation artifacts

- `frames.gv` and `frames.pdf` had no active references and were removed.
- `global_localization_old.cpp` was not part of any CMake target and was removed.
- Console screenshots referenced by the frontend README were moved from Vite's
  `public/` directory to `src/Go2_web_console/docs/screenshots/`. This preserves
  documentation while preventing them from entering the production Web bundle.
- The unreferenced Vite logo and `robot_image.jpg` public files were removed.
- The empty tracked `.codex` marker and old `.codex_backups` directory were
  removed.

Files retained only for local recovery are under the ignored directory
`maps/archive/repository-cleanup-20260810/`; they are not part of the clean
project package.

Historical plans and integration logs were intentionally preserved even when
they mention retired entry points.
