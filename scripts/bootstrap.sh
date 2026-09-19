#!/bin/sh
set -eu
seedbridge_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$seedbridge_root"
uv sync --frozen
seedbridge_compiler="$HOME/.solc-select/artifacts/solc-0.8.36/solc-0.8.36"
if [ ! -x "$seedbridge_compiler" ] && [ -z "${SEEDBRIDGE_SOLC:-}" ]; then
    .venv/bin/solc-select install 0.8.36
fi
mkdir -p .bin
./scripts/prepare-medusa-lineage.sh
cd adapters/medusa
GOTOOLCHAIN=local go build -mod=readonly -o ../../.bin/medusa-adapter .
cd "$seedbridge_root"
./seedbridge doctor --output configs/toolchain.local.json
PYTHONPATH=src uv run --frozen python - <<'PY'
from seedbridge.config import ROOT, SCENARIOS
from seedbridge.medusa import build_fixture
for fixture in SCENARIOS:
    build_fixture(fixture, ROOT / "runs/bootstrap" / fixture, 60)
    print(f"Built fixed fixture: {fixture}")
PY
