"""Persist actual compiler artifacts rather than trusting configured version labels."""

import hashlib
import json
from pathlib import Path

from .doctor import tool_environment
from .io import file_hash, read_json, write_json
from .process import EvidenceMismatchError, ToolExecutionError, run_command


def build_manifest(project: Path, contract: str, directory: Path, timeout: float) -> dict:
    config_path = directory / "foundry-config.json"
    result = run_command(["forge", "config", "--json"], cwd=project, log_path=config_path,
                         stderr_path=directory / "foundry-config.stderr.log",
                         timeout=timeout, env=tool_environment())
    if result.timed_out or result.returncode:
        status = "timeout" if result.timed_out else "tool_error"
        raise ToolExecutionError("Unable to read resolved Foundry configuration", status=status)
    config = read_json(config_path)
    expected = {"evm_version": "shanghai", "optimizer": False, "via_ir": False,
                "bytecode_hash": "ipfs", "cbor_metadata": True}
    if any(config.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Resolved compiler configuration differs from the pinned settings")
    path = project / "out" / f"{contract}.sol" / f"{contract}.json"
    artifact = read_json(path)
    init = bytes.fromhex(artifact["bytecode"]["object"].removeprefix("0x"))
    runtime = bytes.fromhex(artifact["deployedBytecode"]["object"].removeprefix("0x"))
    metadata = artifact.get("metadata")
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not metadata or not metadata["compiler"]["version"].startswith("0.8.36+"):
        raise RuntimeError("Artifact metadata does not confirm the pinned compiler")
    abi = json.dumps(artifact["abi"], sort_keys=True, separators=(",", ":")).encode()
    manifest = {"artifact_path": str(path), "abi_sha256": hashlib.sha256(abi).hexdigest(),
                "source_sha256": file_hash(project / "src" / f"{contract}.sol"),
                "init_sha256": hashlib.sha256(init).hexdigest(),
                "runtime_sha256": hashlib.sha256(runtime).hexdigest(),
                "compiler": metadata["compiler"], "settings": metadata["settings"],
                "resolved_config": str(config_path)}
    write_json(directory / "build-manifest.json", manifest)
    return manifest


def assert_same_target(left: dict, right: dict) -> None:
    for field in ("source_sha256", "abi_sha256", "init_sha256", "runtime_sha256"):
        if left[field] != right[field]:
            raise EvidenceMismatchError(f"Target artifact mismatch: {field}")


def assert_medusa_build(baseline: dict, observation: dict) -> None:
    actual = observation.get("build", {})
    if (actual.get("medusa_build_matches_forge") is not True or
            actual.get("source_sha256") != baseline["source_sha256"] or
            actual.get("init_bytecode_sha256") != baseline["init_sha256"] or
            actual.get("runtime_bytecode_sha256") != baseline["runtime_sha256"]):
        raise EvidenceMismatchError("Medusa execution differs from the baseline source or compiled target")
