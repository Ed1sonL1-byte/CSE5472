"""Delivery-only relocation rejects unsafe paths and altered archive evidence."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/review-stage4-archive.py"
SPEC = importlib.util.spec_from_file_location("stage4_archive_review", SCRIPT)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def make_archive(path, members, *, bad_digest=False, extra=None):
    rows = [{"path": name, "bytes": len(payload),
             "sha256": "0" * 64 if bad_digest else hashlib.sha256(payload).hexdigest()}
            for name, payload, _ in members]
    manifest = {"schema_version": 1, "file_count": len(rows),
                "total_bytes": sum(row["bytes"] for row in rows), "files": rows}
    with tarfile.open(path, "w:gz") as archive:
        data = json.dumps(manifest).encode()
        info = tarfile.TarInfo("archive-manifest.json")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
        for name, payload, kind in members + ([extra] if extra else []):
            info = tarfile.TarInfo(name)
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "../../outside"
                archive.addfile(info)
            else:
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))


def test_relocation_reads_new_bytes_even_when_original_exists(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "record.json").write_text("old")
    (new / "record.json").write_text("new")
    assert review.relocated_path(new, str(old), str(old / "record.json")).read_text() == "new"
    (new / "record.json").unlink()
    with pytest.raises(review.ReviewError, match="missing"):
        review.relocated_path(new, str(old), str(old / "record.json"))


@pytest.mark.parametrize("value", ["/original-sibling/a", "/original/../escape", "relative/a"])
def test_relocation_rejects_bad_original_boundaries(tmp_path, value):
    with pytest.raises(review.ReviewError):
        review.relocated_path(tmp_path, "/original", value)


def test_relocation_rejects_symlink_escape(tmp_path):
    study = tmp_path / "study"
    study.mkdir()
    external = tmp_path / "external"
    external.write_text("outside")
    (study / "record").symlink_to(external)
    with pytest.raises(review.ReviewError, match="escapes"):
        review.relocated_path(study, "/original", "/original/record")


def test_extraction_preserves_exact_bytes(tmp_path):
    archive = tmp_path / "raw.tar.gz"
    make_archive(archive, [("study/a.json", b'{"test": true}\n', "file")])
    result = review.extract_verified(archive, tmp_path / "extracted")
    assert result["file_count"] == 1
    assert (tmp_path / "extracted/study/a.json").read_bytes() == b'{"test": true}\n'


@pytest.mark.parametrize("name,kind", [("../escape", "file"), ("/absolute", "file"),
                                      ("study/link", "symlink")])
def test_extraction_rejects_traversal_and_links(tmp_path, name, kind):
    archive = tmp_path / "raw.tar.gz"
    make_archive(archive, [(name, b"x", kind)])
    with pytest.raises(review.ReviewError):
        review.extract_verified(archive, tmp_path / "extracted")
    assert not (tmp_path / "escape").exists()


def test_extraction_detects_corrupted_payload_digest(tmp_path):
    archive = tmp_path / "raw.tar.gz"
    make_archive(archive, [("study/a.json", b"changed", "file")], bad_digest=True)
    with pytest.raises(review.ReviewError, match="checksum"):
        review.extract_verified(archive, tmp_path / "extracted")


def test_extraction_rejects_unlisted_member(tmp_path):
    archive = tmp_path / "raw.tar.gz"
    make_archive(archive, [("study/a", b"a", "file")], extra=("study/extra", b"b", "file"))
    with pytest.raises(review.ReviewError, match="unlisted"):
        review.extract_verified(archive, tmp_path / "extracted")


def test_wrong_archive_hash_preserves_failure_certificate(tmp_path):
    archive = tmp_path / "raw.tar.gz"
    make_archive(archive, [("study/a", b"a", "file")])
    output = tmp_path / "review"
    with pytest.raises(review.ReviewError, match="SHA-256"):
        review.review_archive(archive, output, "0" * 64)
    certificate = json.loads((output / "review.json").read_text())
    assert certificate["status"] == "failed"
    assert not (output / "extracted").exists()
    with pytest.raises(FileExistsError):
        review.review_archive(archive, output, review.digest(archive))


def test_execution_snapshot_rejects_changed_source(tmp_path):
    study = tmp_path / "study"
    source = study / "execution-source"
    source.mkdir(parents=True)
    name = "auditor.py"
    payload = b"# original\n"
    sha = hashlib.sha256(payload).hexdigest()
    combined = hashlib.sha256(name.encode() + b"\0" + sha.encode() + b"\n").hexdigest()
    snapshot = {"file_count": 1, "content_sha256": combined,
                "files": [{"path": name, "bytes": len(payload), "sha256": sha}]}
    (source / name).write_bytes(payload)
    (source / "source-manifest.json").write_text(json.dumps(snapshot))
    (study / "manifest.json").write_text(json.dumps({"execution_source": snapshot}))
    assert review.verify_execution_source(study) == snapshot
    (source / name).write_bytes(b"# modified\n")
    with pytest.raises(review.ReviewError, match="integrity"):
        review.verify_execution_source(study)
