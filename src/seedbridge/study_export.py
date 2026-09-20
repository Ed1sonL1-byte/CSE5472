"""Create and verify a self-contained offline Stage 3 evidence archive."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _study_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def export_study(root: Path, output: Path) -> dict:
    root = Path(root).resolve()
    output = Path(output).resolve()
    if output.exists() or output.with_suffix(output.suffix + ".sha256").exists():
        raise ValueError("study archive and checksum outputs must be new")
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("status") != "complete":
        raise ValueError("only a complete study can be exported")
    required_source = root / "execution-source/src/seedbridge/study_audit.py"
    required_report = root / "execution-source/src/seedbridge/study_report.py"
    if not required_source.is_file() or not required_report.is_file():
        raise ValueError("frozen execution source does not contain the offline auditor and reporter")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = _study_files(root)
    archive_rows = [
        {
            "path": f"study/{path.relative_to(root).as_posix()}",
            "bytes": path.stat().st_size,
            "sha256": _sha(path),
        }
        for path in files
    ]
    rebuild_source = """#!/usr/bin/env python3
from pathlib import Path
import sys

archive_root = Path(__file__).resolve().parent
sys.path.insert(0, str(archive_root / "study/execution-source/src"))
from seedbridge.study_report import build_study_report

destination = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else archive_root / "rebuilt"
result = build_study_report(archive_root / "study", destination)
print(f"{result['audit_status']}: {result['slot_count']} slots; {result['content_sha256']}")
"""
    readme = """# Stage 3 Offline Evidence Archive

This archive contains the frozen study, compact raw events, accepted seeds, model and replay evidence,
source snapshot, derived reports, and per-file checksums. It requires only Python's standard library.

From the extracted archive root, run:

```sh
python3 rebuild.py rebuilt
```

The command independently audits raw events and rebuilds JSON, CSV, Markdown, and SVG outputs without
Medusa, Halmos, Forge, solc, Z3, Go, or network access. Absolute paths inside historical provenance
fields are informational; the auditor resolves evidence relative to the extracted `study` directory.
"""
    archive_manifest = {
        "schema_version": 1,
        "study_id": manifest["study_id"],
        "study_manifest_sha256": _sha(root / "manifest.json"),
        "file_count": len(archive_rows),
        "total_bytes": sum(row["bytes"] for row in archive_rows),
        "files": archive_rows,
    }
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="seedbridge-export-") as temporary:
        metadata = Path(temporary)
        (metadata / "archive-manifest.json").write_text(
            json.dumps(archive_manifest, indent=2, sort_keys=True) + "\n")
        (metadata / "rebuild.py").write_text(rebuild_source)
        (metadata / "OFFLINE_README.md").write_text(readme)
        with tarfile.open(output, "w:gz", compresslevel=6) as archive:
            archive.add(metadata / "archive-manifest.json", arcname="archive-manifest.json")
            archive.add(metadata / "rebuild.py", arcname="rebuild.py")
            archive.add(metadata / "OFFLINE_README.md", arcname="OFFLINE_README.md")
            for path in files:
                archive.add(path, arcname=f"study/{path.relative_to(root).as_posix()}")
    digest = _sha(output)
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {output.name}\n")
    return {
        "schema_version": 1,
        "status": "created",
        "archive_path": str(output),
        "archive_sha256": digest,
        "archive_bytes": output.stat().st_size,
        "checksum_path": str(checksum_path),
        "study_file_count": len(files),
        "study_bytes": archive_manifest["total_bytes"],
        "elapsed_seconds": time.monotonic() - started,
    }


def verify_archive(archive: Path, destination: Path) -> dict:
    archive = Path(archive).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("archive verification destination must be new")
    destination.mkdir(parents=True)
    started = time.monotonic()
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        for member in members:
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError("archive contains an unsafe member path")
        source.extractall(destination, filter="data")
    manifest = json.loads((destination / "archive-manifest.json").read_text())
    for row in manifest["files"]:
        path = destination / row["path"]
        if (not path.is_file() or path.stat().st_size != row["bytes"]
                or _sha(path) != row["sha256"]):
            raise ValueError(f"archive member checksum differs: {row['path']}")
    outputs = []
    for attempt in (1, 2):
        rebuilt = destination / f"rebuilt-{attempt}"
        result = subprocess.run(
            [shutil.which("python3") or "python3", str(destination / "rebuild.py"), str(rebuilt)],
            cwd=destination, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"offline rebuild failed: {result.stdout}")
        outputs.append({
            "attempt": attempt,
            "stdout": result.stdout.strip(),
            "summary_sha256": _sha(rebuilt / "summary.json"),
            "observations_sha256": _sha(rebuilt / "observations.csv"),
            "markdown_sha256": _sha(rebuilt / "summary.md"),
        })
    if outputs[0]["summary_sha256"] != outputs[1]["summary_sha256"]:
        raise ValueError("two offline summary rebuilds differ")
    if outputs[0]["observations_sha256"] != outputs[1]["observations_sha256"]:
        raise ValueError("two offline observation rebuilds differ")
    return {
        "schema_version": 1,
        "status": "passed",
        "archive_path": str(archive),
        "archive_sha256": _sha(archive),
        "extracted_file_count": manifest["file_count"],
        "rebuilds": outputs,
        "elapsed_seconds": time.monotonic() - started,
    }
