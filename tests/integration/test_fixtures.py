import json
import os

import pytest

from seedbridge.config import get_scenario
from seedbridge.doctor import tool_environment
from seedbridge.process import run_command

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("SEEDBRIDGE_INTEGRATION") != "1", reason="set SEEDBRIDGE_INTEGRATION=1 to run native tools")]


@pytest.mark.parametrize("fixture", ["phase_counter", "bounded_ledger"])
def test_concrete_fixture_suite(fixture, tmp_path):
    scenario = get_scenario(fixture)
    result = run_command(["forge", "test", "--json", "--match-contract", scenario.contract + "Test"],
                         cwd=scenario.root, timeout=60, env=tool_environment(),
                         log_path=tmp_path / "forge.json", stderr_path=tmp_path / "forge.stderr.log")
    assert not result.timed_out and result.returncode == 0
    data = json.loads((tmp_path / "forge.json").read_text())
    tests = [test for contract in data.values() for test in contract.get("test_results", {}).values()]
    assert len(tests) == 4
    assert all(test["status"] == "Success" for test in tests)
