import json

import pytest

from seedbridge.medusa import campaign
from seedbridge.process import CommandResult, EvidenceMismatchError, ToolExecutionError


def test_campaign_preserves_native_tool_error_even_when_report_was_written(tmp_path, monkeypatch):
    directory = tmp_path / "campaign"

    def failed(command, *, cwd, log_path, timeout, env):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "campaign.json").write_text(json.dumps({
            "schema_version": 2,
            "medusa_version": "v1.5.1",
            "fixture": "phase_counter",
            "status": "tool_error",
            "error": "native worker failed during timeout shutdown",
            "completed_sequences": 7,
            "sequences": [],
            "deployment": {},
        }))
        return CommandResult(command, 1, 0.2, False, str(log_path))

    monkeypatch.setattr("seedbridge.medusa.run_command", failed)
    with pytest.raises(ToolExecutionError, match="native worker failed") as raised:
        campaign(
            "phase_counter", directory, seed=1, tests=10, fuzz_timeout=1,
            process_timeout=2, corpus=tmp_path / "corpus", record_lineage=False,
        )
    assert raised.value.status == "tool_error"


def test_compact_campaign_missing_completion_is_evidence_error(tmp_path, monkeypatch):
    directory = tmp_path / "campaign"

    def incomplete(command, *, cwd, log_path, timeout, env):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "campaign.json").write_text(json.dumps({
            "schema_version": 3,
            "medusa_version": "v1.5.1",
            "fixture": "phase_counter",
            "status": "timeout",
            "stop_reason": "time_limit",
            "completed_sequences": 0,
            "sequences": [],
            "deployment": {},
            "compact_events": {},
        }))
        return CommandResult(command, 1, 0.2, False, str(log_path))

    monkeypatch.setattr("seedbridge.medusa.run_command", incomplete)
    monkeypatch.setattr(
        "seedbridge.medusa.read_compact_events",
        lambda *_args: {"sequences": [], "lineage": [], "partial_sequences": []},
    )
    with pytest.raises(EvidenceMismatchError, match="completion timing") as raised:
        campaign(
            "phase_counter", directory, seed=1, tests=10000, fuzz_timeout=1,
            process_timeout=2, corpus=tmp_path / "corpus", compact=True,
        )
    assert raised.value.status == "evidence_error"
