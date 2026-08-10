#!/usr/bin/env python3
"""Validate and atomically promote the canonical FAST-LIO/Nav2 map bundle.

The manifest is JSON stored in ``map_manifest.yaml``. JSON is valid YAML 1.2,
while keeping this safety-critical utility limited to the Python standard
library available on the Jetson.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


DATA_FILES = ("MID360.pcd", "MID360_map.pgm", "MID360_map.yaml")
MANIFEST_NAME = "map_manifest.yaml"
ALL_FILES = (*DATA_FILES, MANIFEST_NAME)


class BundleError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_file(root: Path, name: str) -> Path:
    path = root / name
    if not path.is_file() or path.stat().st_size <= 0:
        raise BundleError(f"map bundle is missing non-empty {name}")
    return path


def create_manifest(root: Path | str, *, bundle_id: str) -> dict:
    root = Path(root)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", bundle_id):
        raise BundleError("bundle_id contains unsupported characters")
    files = {}
    for name in DATA_FILES:
        path = _required_file(root, name)
        files[name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    manifest = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
    }
    target = root / MANIFEST_NAME
    temporary = root / f".{MANIFEST_NAME}.tmp"
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return manifest


def validate_bundle(root: Path | str) -> dict:
    root = Path(root)
    manifest_path = _required_file(root, MANIFEST_NAME)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BundleError("map manifest is not valid JSON-compatible YAML") from exc
    if manifest.get("schema_version") != 1:
        raise BundleError("unsupported map manifest schema_version")
    if not isinstance(manifest.get("bundle_id"), str):
        raise BundleError("map manifest is missing bundle_id")
    records = manifest.get("files")
    if not isinstance(records, dict) or set(records) != set(DATA_FILES):
        raise BundleError("map manifest must list exactly the canonical files")

    for name in DATA_FILES:
        path = _required_file(root, name)
        record = records.get(name)
        if not isinstance(record, dict):
            raise BundleError(f"invalid manifest record for {name}")
        if record.get("bytes") != path.stat().st_size:
            raise BundleError(f"size mismatch for {name}")
        if record.get("sha256") != _sha256(path):
            raise BundleError(f"SHA-256 mismatch for {name}")

    yaml_text = (root / "MID360_map.yaml").read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*image\s*:\s*(.+?)\s*$", yaml_text)
    if match is None:
        raise BundleError("MID360_map.yaml is missing image")
    image = match.group(1).strip().strip("\"'")
    if Path(image).name != "MID360_map.pgm":
        raise BundleError("MID360_map.yaml must reference MID360_map.pgm")
    return manifest


def _archive_active(active: Path, archive_root: Path, manifest: dict) -> None:
    if not any((active / name).exists() for name in ALL_FILES):
        return
    validate_bundle(active)
    target = archive_root / manifest["bundle_id"]
    if target.exists():
        raise BundleError(f"archive already exists: {target}")
    archive_root.mkdir(parents=True, exist_ok=True)
    temporary = archive_root / f".{target.name}.tmp-{os.getpid()}"
    temporary.mkdir()
    try:
        for name in ALL_FILES:
            shutil.copy2(active / name, temporary / name)
        validate_bundle(temporary)
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def promote_bundle(
    staging: Path | str,
    active: Path | str,
    archive_root: Path | str,
) -> dict:
    staging = Path(staging)
    active = Path(active)
    archive_root = Path(archive_root)
    incoming_manifest = validate_bundle(staging)
    active.mkdir(parents=True, exist_ok=True)

    current = None
    if any((active / name).exists() for name in ALL_FILES):
        current = validate_bundle(active)
        _archive_active(active, archive_root, current)

    incoming_dir = Path(
        tempfile.mkdtemp(prefix=".map-incoming-", dir=str(active))
    )
    try:
        for name in ALL_FILES:
            shutil.copy2(staging / name, incoming_dir / name)
        validate_bundle(incoming_dir)
        # The manifest is the commit marker: readers validate it after the
        # three payload replacements and therefore never accept a mixed set.
        for name in DATA_FILES:
            os.replace(incoming_dir / name, active / name)
        os.replace(incoming_dir / MANIFEST_NAME, active / MANIFEST_NAME)
        return validate_bundle(active)
    except Exception as exc:
        if current is not None:
            archived = archive_root / current["bundle_id"]
            for name in DATA_FILES:
                if (archived / name).is_file():
                    shutil.copy2(archived / name, active / name)
            shutil.copy2(archived / MANIFEST_NAME, active / MANIFEST_NAME)
        else:
            for name in ALL_FILES:
                try:
                    (active / name).unlink()
                except FileNotFoundError:
                    pass
        if isinstance(exc, BundleError):
            raise
        raise BundleError(f"map promotion failed: {exc}") from exc
    finally:
        shutil.rmtree(incoming_dir, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("root", type=Path)
    manifest_parser = subparsers.add_parser("create-manifest")
    manifest_parser.add_argument("root", type=Path)
    manifest_parser.add_argument("--bundle-id", required=True)
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("staging", type=Path)
    promote_parser.add_argument("active", type=Path)
    promote_parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_bundle(args.root)
        elif args.command == "create-manifest":
            result = create_manifest(args.root, bundle_id=args.bundle_id)
        else:
            result = promote_bundle(args.staging, args.active, args.archive)
    except BundleError as exc:
        print(f"map bundle error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
