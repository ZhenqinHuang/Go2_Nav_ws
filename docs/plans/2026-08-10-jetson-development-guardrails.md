# Jetson Development Guardrails Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add one operator-facing Markdown reference that preserves the Go2 Jetson network, ROS, map, Web, deployment, and physical-control boundaries for future development.

**Architecture:** Keep the guardrails in one document at `docs/jetson-development-guardrails.md` and link it from the root README. Reuse the canonical facts already recorded in architecture, deployment, operations, troubleshooting, and verification documents; do not introduce new runtime mechanisms.

**Tech Stack:** Markdown, Git, repository interface tests.

---

### Task 1: Add the Jetson development guardrails

**Files:**
- Create: `docs/jetson-development-guardrails.md`
- Modify: `README.md`
- Test: `test/interface/test_project_layout.py`

**Step 1: Write the failing documentation contract test**

Add a test asserting that the guardrails document exists, is linked from `README.md`, and contains the critical literals `192.168.0.101`, `192.168.123.5`, `192.168.1.5`, `map -> odom -> base_link`, `go2-motion-sender.service`, `map_manifest.yaml`, `emergency-stop`, and `staging`.

**Step 2: Run the test and confirm RED**

Run:

```bash
python -m pytest -q test/interface/test_project_layout.py
```

Expected: failure because `docs/jetson-development-guardrails.md` does not exist.

**Step 3: Write the minimal complete document**

Create the document with these sections:

1. scope and immutable architecture summary;
2. network/interface/address/route table;
3. external Jetson, internal gateway, and Go2 responsibility boundary;
4. motion safety, e-stop, watchdog, posture, and authorization rules;
5. ROS topic, TF, frame, QoS, and owner rules;
6. canonical map bundle and atomic promotion rules;
7. Web/API/authentication/control-lease rules;
8. workspace, systemd, staging, build, and rollback rules;
9. allowed zero-motion checks and explicitly authorized physical tests;
10. power-on, pre-motion, and pre-commit checklists;
11. diagnostic commands and a short “never do this” list.

Do not include passwords or commands that bypass the UDP gateway.

**Step 4: Link it from the root README**

Add `Jetson 后续开发边界` to the existing documentation list.

**Step 5: Verify GREEN and repository integrity**

Run:

```bash
python -m pytest -q test/interface/test_project_layout.py
python scripts/map_bundle.py validate maps
git diff --check
```

Expected: all tests pass, map validation succeeds, and no whitespace errors are reported.

**Step 6: Commit**

```bash
git add README.md docs/jetson-development-guardrails.md test/interface/test_project_layout.py
git commit -m "docs: add Jetson development guardrails"
```
