#!/usr/bin/env python3
"""Record the Stage 3 starting source and immutable Stage 2 evidence inventory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/stage3/baseline.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def source_paths() -> list[Path]:
    paths: set[Path] = set()
    for pattern in (
        "src/seedbridge/*.py", "adapters/medusa/*.go", "adapters/medusa/go.mod",
        "adapters/medusa/go.sum", "adapters/medusa/patches/*.patch", "fixtures/*/src/*.sol",
        "fixtures/*/foundry.toml", "configs/*.json", "scripts/*.py", "scripts/*.sh",
        "pyproject.toml", "uv.lock", ".python-version",
    ):
        paths.update(path for path in ROOT.glob(pattern) if path.is_file())
    return sorted(paths)


def duplicate_inventory() -> list[dict]:
    result = []
    evidence = ROOT / "evidence/stage2"
    for path in sorted(evidence.iterdir()):
        if " 2." not in path.name and " 3." not in path.name:
            continue
        official_name = path.name.replace(" 2.", ".").replace(" 3.", ".")
        official = evidence / official_name
        result.append({
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
            "official_path": str(official.relative_to(ROOT)) if official.is_file() else None,
            "identical_to_official": official.is_file() and digest(path) == digest(official),
        })
    return result


def stage2_raw_inventory() -> list[dict]:
    formal = ROOT / "runs/stage2-formal-02"
    paths = [formal / "manifest.json", formal / "audit.json"]
    paths.extend(sorted(formal.glob("blocks/*/repeat-*/warmup/common.json")))
    paths.extend(sorted(formal.glob("blocks/*/repeat-*/warmup/warmup/campaign.json")))
    paths.extend(sorted(formal.glob("blocks/*/repeat-*/arms/*/campaign.json")))
    paths.append(ROOT / "runs/stage2-p1-mechanism/campaign-01.json")
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Stage 2 baseline files are missing: {missing}")
    return [{
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
    } for path in paths]


def main() -> int:
    inventory = source_paths()
    document = {
        "schema_version": 1,
        "stage3_start_commit": "abad61ad9039890eeddd3c11bdb1575faf602ad6",
        "observed_git_head": git("rev-parse", "HEAD"),
        "git_status": git("status", "--porcelain=v1"),
        "source_inventory": [{
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        } for path in inventory],
        "stage2_raw_inventory": stage2_raw_inventory(),
        "unrelated_stage2_duplicates": duplicate_inventory(),
        "notes": [
            "Stage 2 raw campaign files are read-only inputs for Stage 3.",
            "Files with ' 2' or ' 3' suffixes are inventoried but excluded from official evidence.",
            "Formal Stage 3 archives must include a fresh execution-source snapshot, not only this baseline.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
