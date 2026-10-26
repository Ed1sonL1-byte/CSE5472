#!/usr/bin/env python3
"""Verify, relocate, and independently re-audit the frozen Stage 4 archive.

Only the archived auditor's evidence-path resolver is replaced in memory. No
archived bytes, experimental semantics, or original filesystem paths are changed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
MAX_MANIFEST_BYTES = 64 * 1024 * 1024


class ReviewError(ValueError):
    pass


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ReviewError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def checked_digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ReviewError("expected a 64-character SHA-256")
    return value.lower()


def relative_name(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ReviewError("invalid archive-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ReviewError(f"unsafe relative path: {value}")
    if ":" in path.parts[0]:
        raise ReviewError(f"unsafe relative path: {value}")
    return path


def relocated_path(study: Path, old_root: str, value: str) -> Path:
    """Map by lexical prefix; never read or resolve the original machine path."""
    if not isinstance(value, str) or "\\" in value or "\0" in value:
        raise ReviewError("invalid recorded evidence path")
    original = PurePosixPath(value)
    previous = PurePosixPath(old_root)
    if (not original.is_absolute() or not previous.is_absolute()
            or ".." in original.parts or ".." in previous.parts):
        raise ReviewError("recorded evidence path must be absolute without traversal")
    try:
        relative = original.relative_to(previous)
    except ValueError as error:
        raise ReviewError(f"recorded path is outside the original study: {value}") from error
    root = study.resolve(strict=True)
    try:
        target = root.joinpath(*relative.parts).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ReviewError(f"relocated evidence is missing: {value}") from error
    if not target.is_relative_to(root) or not target.is_file():
        raise ReviewError(f"relocated evidence escapes the study or is not a file: {value}")
    return target


def extract_verified(archive_path: Path, destination: Path) -> dict:
    destination.mkdir()
    with tarfile.open(archive_path, "r|gz") as archive:
        first = archive.next()
        if (first is None or first.name != "archive-manifest.json" or not first.isfile()
                or not 0 < first.size <= MAX_MANIFEST_BYTES):
            raise ReviewError("archive must start with a bounded regular-file manifest")
        stream = archive.extractfile(first)
        if stream is None:
            raise ReviewError("cannot read archive manifest")
        manifest_bytes = stream.read()
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ReviewError("unsupported archive manifest schema")
        rows = manifest.get("files")
        if not isinstance(rows, list) or manifest.get("file_count") != len(rows):
            raise ReviewError("archive manifest file count is inconsistent")
        expected = {}
        for row in rows:
            name = relative_name(row["path"]).as_posix()
            if (name in expected or name == "archive-manifest.json"
                    or type(row.get("bytes")) is not int or row["bytes"] < 0):
                raise ReviewError("duplicate archive path or invalid file size")
            checked_digest(row["sha256"])
            expected[name] = row
        total_bytes = sum(row["bytes"] for row in rows)
        if manifest.get("total_bytes") != total_bytes:
            raise ReviewError("archive manifest byte count is inconsistent")
        if shutil.disk_usage(destination).free < total_bytes + MAX_MANIFEST_BYTES:
            raise ReviewError("insufficient free space for verified extraction")
        (destination / "archive-manifest.json").write_bytes(manifest_bytes)
        seen = set()
        for member in iter(archive.next, None):
            name = relative_name(member.name).as_posix()
            if not member.isfile() or name not in expected or name in seen:
                raise ReviewError(f"unlisted, duplicate, or non-regular archive member: {name}")
            row = expected[name]
            if member.size != row["bytes"]:
                raise ReviewError(f"archive member size mismatch: {name}")
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ReviewError(f"cannot read archive member: {name}")
            value = hashlib.sha256()
            written = 0
            with target.open("xb") as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(chunk)
                    value.update(chunk)
                    written += len(chunk)
            if written != row["bytes"] or value.hexdigest() != row["sha256"]:
                raise ReviewError(f"archive member checksum mismatch: {name}")
            seen.add(name)
        if seen != set(expected):
            raise ReviewError("archive is missing listed members")
    return manifest


def verify_execution_source(study: Path) -> dict:
    study_manifest = read_json(study / "manifest.json")
    source = study / "execution-source"
    snapshot = read_json(source / "source-manifest.json")
    if snapshot != study_manifest.get("execution_source"):
        raise ReviewError("archived source manifest differs from the study manifest")
    rows = snapshot.get("files")
    if not isinstance(rows, list) or snapshot.get("file_count") != len(rows):
        raise ReviewError("execution-source file count differs")
    combined = hashlib.sha256()
    names = set()
    for row in rows:
        name = relative_name(row["path"]).as_posix()
        path = source.joinpath(*PurePosixPath(name).parts)
        if (name in names or not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to(source.resolve())
                or path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]):
            raise ReviewError(f"execution-source integrity mismatch: {name}")
        combined.update(name.encode() + b"\0" + row["sha256"].encode() + b"\n")
        names.add(name)
    actual = {path.relative_to(source).as_posix() for path in source.rglob("*")
              if path.is_file() and path != source / "source-manifest.json"}
    if actual != names or combined.hexdigest() != snapshot.get("content_sha256"):
        raise ReviewError("execution-source inventory or aggregate digest differs")
    return snapshot


def audit_worker(study: Path, output: Path) -> dict:
    sys.dont_write_bytecode = True
    study = study.resolve(strict=True)
    if output.resolve().is_relative_to(study):
        raise ReviewError("audit output must be outside the frozen study")
    verify_execution_source(study)
    manifest = read_json(study / "manifest.json")
    recorded_config = PurePosixPath(manifest["frozen_config_path"])
    if (not recorded_config.is_absolute() or recorded_config.name != "frozen-config.json"
            or ".." in recorded_config.parts):
        raise ReviewError("invalid original frozen-config path")
    old_root = str(recorded_config.parent)
    source = study / "execution-source/src"
    if any(name == "seedbridge" or name.startswith("seedbridge.") for name in sys.modules):
        raise ReviewError("worker must start without an imported SeedBridge package")
    sys.path.insert(0, str(source))
    auditor = importlib.import_module("seedbridge.safety_audit")
    for name in ("seedbridge", "seedbridge.io", "seedbridge.study_audit", "seedbridge.safety_audit"):
        if not Path(sys.modules[name].__file__).resolve().is_relative_to(source):
            raise ReviewError("auditor was not imported from the verified snapshot")
    original_resolver = auditor._inside
    resolved_count = 0

    def resolver(root: Path, value: str) -> Path:
        nonlocal resolved_count
        if root.resolve() != study:
            raise ReviewError("auditor requested an unexpected study root")
        path = relocated_path(study, old_root, value)
        resolved_count += 1
        return path

    auditor._inside = resolver
    try:
        result = auditor.audit_safety_study(study)
    finally:
        auditor._inside = original_resolver
    write_json(output, result)
    archived = read_json(study / "derived/audit.json")
    if result != archived or result.get("status") != "passed" or result.get("slot_count") != 60:
        raise ReviewError("recomputed raw audit differs from archived audit or lacks 60 valid slots")
    return {"status": "passed", "raw_audit_equal": True,
            "slot_count": result["slot_count"], "common_block_count": result["common_block_count"],
            "complete_sequence_count": result["complete_sequence_count"],
            "mutation_event_count": result["mutation_event_count"],
            "relocated_path_reads": resolved_count,
            "path_adapter": "only safety_audit._inside replaced in memory; no original-path fallback",
            "auditor_source": "verified archived execution-source"}


def review_archive(archive: Path, output: Path, expected_sha256: str) -> dict:
    archive = archive.resolve(strict=True)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    certificate = {"schema_version": 1, "status": "running", "archive": str(archive),
                   "expected_sha256": checked_digest(expected_sha256),
                   "method": "verified extraction and frozen raw auditor with explicit path relocation"}
    try:
        actual_sha = digest(archive)
        certificate.update(archive_sha256=actual_sha, archive_bytes=archive.stat().st_size)
        if actual_sha != certificate["expected_sha256"]:
            raise ReviewError("archive SHA-256 differs from the expected public or explicit value")
        manifest = extract_verified(archive, output / "extracted")
        certificate.update(archived_file_count=manifest["file_count"],
                           archived_source_bytes=manifest["total_bytes"])
        study = output / "extracted/study"
        source = verify_execution_source(study)
        certificate.update(execution_source_file_count=source["file_count"],
                           execution_source_sha256=source["content_sha256"])
        with (output / "worker.stdout.log").open("w") as stdout, \
                (output / "worker.stderr.log").open("w") as stderr:
            command = subprocess.run(
                [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--audit-worker",
                 "--study", str(study), "--audit-output", str(output / "recomputed-audit.json")],
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, check=False,
            )
        if command.returncode != 0:
            raise ReviewError(f"frozen raw audit failed; see {output / 'worker.stderr.log'}")
        worker = read_json(output / "worker.stdout.log")
        certificate.update(worker)
        certificate["recomputed_audit_sha256"] = digest(output / "recomputed-audit.json")
        write_json(output / "review.json", certificate)
        return certificate
    except Exception as error:
        certificate.update(status="failed", error=f"{type(error).__name__}: {error}")
        write_json(output / "review.json", certificate)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path, help="new review directory; never reuses an existing path")
    parser.add_argument("--expected-sha256", help="explicit trusted checksum; defaults to public Stage 4 metadata")
    parser.add_argument("--audit-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--study", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--audit-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.audit_worker:
            if args.study is None or args.audit_output is None:
                parser.error("internal worker requires --study and --audit-output")
            result = audit_worker(args.study, args.audit_output)
        else:
            if args.archive is None or args.output is None:
                parser.error("--archive and --output are required")
            expected = args.expected_sha256
            if expected is None:
                public = read_json(ROOT / "evidence/stage4/archive.json")
                if public.get("schema_version") != 1:
                    raise ReviewError("unsupported public archive metadata schema")
                expected = public["sha256"]
            result = review_archive(args.archive, args.output, checked_digest(expected))
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
