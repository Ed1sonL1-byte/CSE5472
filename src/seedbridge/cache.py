"""Isolated fixture-cache copies and storage safeguards for Stage 3."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import time

from .config import get_scenario


IGNORED_NAMES = {".DS_Store", "__pycache__", "crytic-export"}


def tree_manifest(root: Path) -> dict:
    root = Path(root).resolve()
    files = []
    combined = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if any(part in IGNORED_NAMES for part in path.relative_to(root).parts):
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
        combined.update(relative.encode())
        combined.update(b"\0")
        combined.update(digest.encode())
        combined.update(b"\n")
    return {
        "schema_version": 1,
        "root": str(root),
        "file_count": len(files),
        "byte_count": sum(row["bytes"] for row in files),
        "content_sha256": combined.hexdigest(),
        "files": files,
    }


def create_fixture_base(fixture_id: str, destination: Path) -> dict:
    scenario = get_scenario(fixture_id)
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("fixture cache base destination must be new")
    started = time.monotonic()
    shutil.copytree(
        scenario.root, destination,
        ignore=shutil.ignore_patterns("out", "cache", "crytic-export", ".DS_Store"),
    )
    elapsed = time.monotonic() - started
    result = tree_manifest(destination)
    result.update({"copy_elapsed_seconds": elapsed, "fixture_id": fixture_id})
    return result


def copy_isolated_workspace(source: Path, destination: Path) -> dict:
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("isolated workspace destination must be new")
    before = tree_manifest(source)
    started = time.monotonic()
    shutil.copytree(source, destination)
    elapsed = time.monotonic() - started
    after = tree_manifest(destination)
    if before["content_sha256"] != after["content_sha256"] or before["file_count"] != after["file_count"]:
        raise ValueError("isolated workspace copy differs from its cache base")
    return {
        "schema_version": 1,
        "source": str(source),
        "destination": str(destination),
        "copy_elapsed_seconds": elapsed,
        "source_content_sha256": before["content_sha256"],
        "destination_content_sha256": after["content_sha256"],
        "file_count": after["file_count"],
        "byte_count": after["byte_count"],
    }


def storage_preflight(path: Path, *, minimum_free_bytes: int,
                      maximum_study_bytes: int) -> dict:
    usage = shutil.disk_usage(Path(path).resolve().parent)
    ok = usage.free >= minimum_free_bytes and maximum_study_bytes <= usage.free
    return {
        "schema_version": 1,
        "path": str(Path(path).resolve()),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "minimum_free_bytes": minimum_free_bytes,
        "maximum_study_bytes": maximum_study_bytes,
        "ok": ok,
        "reason": None if ok else "configured storage safeguards exceed available space",
    }


def write_manifest(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
