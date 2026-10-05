#!/usr/bin/env python3
"""Save and verify complete local Stage 4 raw evidence with per-file digests."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def export(study: Path, demo: Path, output: Path) -> dict:
    study, demo, output = study.resolve(), demo.resolve(), output.resolve()
    if output.exists() or output.with_suffix(output.suffix + ".sha256").exists():
        raise ValueError("Stage 4 archive output must be new")
    formal = json.loads((study / "manifest.json").read_text())
    audit = json.loads((study / "derived/audit.json").read_text())
    acceptance = json.loads((demo / "report.json").read_text())
    if (formal.get("status") != "complete" or formal.get("evaluation_valid_count") != 60
            or audit.get("status") != "passed" or audit.get("slot_count") != 60
            or acceptance.get("status") != "safety_confirmed"):
        raise ValueError("Stage 4 acceptance and 60-slot audit must pass before archiving")
    rows = []
    for name, directory in (("study", study), ("demo", demo)):
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            rows.append({"path": f"{name}/{path.relative_to(directory).as_posix()}",
                         "bytes": path.stat().st_size, "sha256": digest(path),
                         "source": path})
    manifest = {"schema_version": 1, "study_id": formal["study_id"],
                "slot_count": 60, "acceptance_status": "safety_confirmed",
                "file_count": len(rows), "total_bytes": sum(row["bytes"] for row in rows),
                "files": [{key: row[key] for key in ("path", "bytes", "sha256")} for row in rows]}
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    if temporary.exists():
        raise ValueError("previous partial archive exists")
    try:
        with tarfile.open(temporary, "w:gz", compresslevel=6) as archive:
            info = tarfile.TarInfo("archive-manifest.json")
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
            for row in rows:
                archive.add(row["source"], arcname=row["path"], recursive=False)
        temporary.rename(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    archive_sha = digest(output)
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(f"{archive_sha}  {output.name}\n")
    return {"status": "created", "archive_path": str(output),
            "sha256": archive_sha, "bytes": output.stat().st_size,
            "file_count": len(rows), "source_bytes": manifest["total_bytes"]}


def verify(path: Path) -> dict:
    path = path.resolve()
    with tarfile.open(path, "r:gz") as archive:
        first = archive.next()
        if first is None or first.name != "archive-manifest.json":
            raise ValueError("Stage 4 archive is missing its manifest")
        source = archive.extractfile(first)
        if source is None:
            raise ValueError("Stage 4 archive manifest is unreadable")
        manifest = json.loads(source.read())
        expected = manifest["files"]
        for row in expected:
            member = archive.next()
            if member is None or member.name != row["path"] or member.size != row["bytes"]:
                raise ValueError("archive member differs from its manifest")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("archive member is unreadable")
            value = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
            if value.hexdigest() != row["sha256"]:
                raise ValueError("archive member checksum differs")
        if archive.next() is not None:
            raise ValueError("archive has unlisted files")
    return {"status": "passed", "archive_path": str(path), "sha256": digest(path),
            "file_count": len(expected)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", type=Path, default=ROOT / "runs/stage4-formal-v2")
    parser.add_argument("--demo", type=Path, default=ROOT / "runs/stage4-demo-smoke-01")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/stage4-formal-v2.tar.gz")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = verify(args.verify) if args.verify else export(args.study, args.demo, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
