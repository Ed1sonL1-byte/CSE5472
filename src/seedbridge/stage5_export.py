"""Path-mapped, checksummed Stage 5 raw archive and fresh-directory audit."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import zipfile

from .io import file_hash, write_json
from .stage5_audit import audit_stage5, write_stage5_results


def export_stage5_archive(study: Path, archive: Path, *,
                          allow_incomplete: bool = False) -> dict:
    study, archive = Path(study).resolve(), Path(archive).resolve()
    if not (study / "manifest.json").is_file():
        raise ValueError("Stage 5 study manifest is missing")
    if archive.exists():
        raise ValueError("archive output must be new")
    audit = audit_stage5(study, require_complete=not allow_incomplete)
    if audit["status"] != "passed":
        raise ValueError("only independently audited formal studies can be archived")
    files = sorted(path for path in study.rglob("*") if path.is_file())
    for path in files:
        if path.is_symlink():
            raise ValueError(f"archive contains symlink: {path}")
    rows = [{"path": path.relative_to(study).as_posix(),
             "bytes": path.stat().st_size, "sha256": file_hash(path)}
            for path in files]
    map_bytes = (json.dumps({"schema_version": 1, "original_root": str(study)},
                            sort_keys=True, indent=2) + "\n").encode()
    if any(row["path"] == "path-map.json" for row in rows):
        raise ValueError("study already has a path-map file")
    rows.append({"path": "path-map.json", "bytes": len(map_bytes),
                 "sha256": hashlib.sha256(map_bytes).hexdigest()})
    package = {"schema_version": 1, "study_id": audit["study_id"],
               "slot_count": audit["slot_count"], "source_root": str(study),
               "complete_matrix": not allow_incomplete,
               "files": rows}
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as target:
        for path in files:
            target.write(path, "study/" + path.relative_to(study).as_posix())
        target.writestr("study/path-map.json", map_bytes)
        target.writestr("archive-manifest.json",
                        json.dumps(package, indent=2, sort_keys=True) + "\n")
    return {"archive": str(archive), "sha256": file_hash(archive),
            "file_count": len(rows), "slot_count": audit["slot_count"]}


def verify_stage5_archive(archive: Path, output: Path) -> dict:
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("verification output must be a new directory")
    output.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        members = source.namelist()
        if (len(members) != len(set(members)) or
                any(name.startswith("/") or ".." in Path(name).parts for name in members)):
            raise ValueError("archive has duplicate or unsafe paths")
        package = json.loads(source.read("archive-manifest.json"))
        expected = {"study/" + row["path"] for row in package["files"]}
        if set(members) != expected | {"archive-manifest.json"}:
            raise ValueError("archive content differs from its file manifest")
        source.extractall(output)
    study = output / "study"
    for row in package["files"]:
        path = study / row["path"]
        if (not path.is_file() or path.stat().st_size != row["bytes"]
                or file_hash(path) != row["sha256"]):
            raise ValueError(f"archive file failed checksum: {row['path']}")
    if package["source_root"] == str(study):
        raise ValueError("archive verification did not use a new directory")
    audit = audit_stage5(study, output / "audit.json",
                         require_complete=package.get("complete_matrix") is True)
    write_stage5_results(audit, output / "derived")
    result = {"schema_version": 1, "status": audit["status"],
              "slot_count": audit["slot_count"], "file_count": len(package["files"]),
              "archive_sha256": file_hash(archive), "extracted_study": str(study)}
    write_json(output / "verification.json", result)
    return result
