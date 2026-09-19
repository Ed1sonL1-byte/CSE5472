"""Read-only checks; setup/install is an explicit bootstrap operation."""

import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from .config import ROOT, SCENARIOS
from .io import file_hash


def tool_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("FOUNDRY_", "DAPP_", "HALMOS_"))}
    environment["PATH"] = os.pathsep.join([
        str(ROOT / ".bin"), str(ROOT / ".venv" / "bin"), environment.get("PATH", "")
    ])
    native_solc = Path.home() / ".solc-select/artifacts/solc-0.8.36/solc-0.8.36"
    solc = environment.get("SEEDBRIDGE_SOLC") or (
        str(native_solc) if native_solc.is_file() else shutil.which("solc", path=environment["PATH"]))
    if solc:
        environment["FOUNDRY_SOLC"] = solc
    environment["SOLC_VERSION"] = "0.8.36"
    environment["FOUNDRY_OFFLINE"] = "true"
    environment["FOUNDRY_PROFILE"] = "default"
    environment["FOUNDRY_EVM_VERSION"] = "shanghai"
    environment["FOUNDRY_OPTIMIZER"] = "false"
    environment["FOUNDRY_VIA_IR"] = "false"
    environment["FOUNDRY_BYTECODE_HASH"] = "ipfs"
    environment["FOUNDRY_CBOR_METADATA"] = "true"
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def inspect_toolchain() -> dict:
    environment = tool_environment()
    checks = {
        "forge": (["--version"], r"Version: 1\.3\.2\b"),
        "solc": (["--version"], r"Version: 0\.8\.36\b"),
        "halmos": (["--version"], r"\b0\.3\.3\b"),
        "crytic-compile": (["--version"], r"\b0\.3\.11\b"),
        "z3": (["--version"], r"\b4\.12\.6\b"),
        "go": (["version"], r"go1\.26\.4\b"),
        "medusa-adapter": (["version"], r"v1\.5\.1"),
    }
    tools = {}
    for name, (args, expected) in checks.items():
        path = environment.get("FOUNDRY_SOLC") if name == "solc" else shutil.which(name, path=environment["PATH"])
        info = {"path": path, "ok": False}
        if path:
            try:
                result = subprocess.run([path, *args], capture_output=True, text=True,
                                        timeout=15, env=environment, cwd=ROOT)
                version = (result.stdout + result.stderr).strip()
                info.update(version=version, returncode=result.returncode,
                            sha256=file_hash(Path(path)),
                            ok=result.returncode == 0 and bool(re.search(expected, version)))
            except (OSError, subprocess.TimeoutExpired) as error:
                info["error"] = str(error)
        tools[name] = info
    python_ok = sys.version_info[:2] == (3, 12)
    return {
        "schema_version": 1,
        "ok": python_ok and all(item["ok"] for item in tools.values()),
        "python": {"version": platform.python_version(), "path": sys.executable, "ok": python_ok},
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "tools": tools,
        "fixtures": {
            name: {"source_sha256": file_hash(scenario.source_file),
                   "foundry_sha256": file_hash(scenario.root / "foundry.toml")}
            for name, scenario in SCENARIOS.items()
        },
        "lockfiles": {name: file_hash(ROOT / name) for name in
                      ["uv.lock", "adapters/medusa/go.mod", "adapters/medusa/go.sum"]
                      if (ROOT / name).is_file()},
        "build": {"solc": "0.8.36", "evm_version": "shanghai", "optimizer": False},
        "notes": ["Version checks do not establish cross-executor compatibility.",
                  "The locked Python environment supplies Z3 4.12.6; the global Z3 is not used."],
    }
