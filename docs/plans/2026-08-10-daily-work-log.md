# Daily Integration Work Log Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a two-layer Markdown log that accurately records the Go2 navigation/Web integration work completed on 2026-08-10.

**Architecture:** Keep the management summary and technical evidence in one file at `docs/work-log-2026-08-10.md`, then link it from the root README. Derive all facts from committed documentation, Git history, and the verification report; do not include credentials or claim unperformed physical tests.

**Tech Stack:** Markdown, Git, pytest documentation contract.

---

### Task 1: Create and verify the daily work log

**Files:**
- Create: `docs/work-log-2026-08-10.md`
- Modify: `README.md`
- Test: `test/interface/test_project_layout.py`

**Step 1: Add the failing contract test**

Add a test asserting that `docs/work-log-2026-08-10.md` exists, is linked from `README.md`, and contains
the literals `管理摘要`, `技术明细`, `FAST-LIO2`, `go2-motion-sender.service`, `a9e7854`,
`103 passed`, `70 passed`, `25 passed`, `staging`, `现网尚未切换`, and `实机运动尚未授权`.

**Step 2: Run the test and verify RED**

```bash
python -m pytest -q test/interface/test_project_layout.py
```

Expected: failure because the work-log file does not exist.

**Step 3: Write the management summary**

Record the day's objective, completed deliverables, current operational state, key risk, and immediate next
steps. Explicitly distinguish committed code, verified staging, untouched production services, and deferred
physical testing.

**Step 4: Write the technical details**

Cover the pipeline, Web/API safety, UDP gateway, atomic map bundle, DWB/RPP and waypoint support, bringup and
systemd consolidation, conservative cleanup, commit history, local/Jetson verification, CRLF Manifest bug,
runtime network observations, deferred physical checks, and the separately dispatched guardrails task.

**Step 5: Link the log from README**

Add `2026-08-10 工作日志` to the root documentation list.

**Step 6: Verify GREEN**

```bash
python -m pytest -q test/interface/test_project_layout.py
python scripts/map_bundle.py validate maps
git diff --check
```

Expected: all checks pass.

**Step 7: Commit**

```bash
git add README.md docs/work-log-2026-08-10.md test/interface/test_project_layout.py
git commit -m "docs: add 2026-08-10 integration work log"
```
