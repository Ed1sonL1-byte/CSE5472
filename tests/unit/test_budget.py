import pytest

from seedbridge.budget import BudgetLedger, CampaignDeadlineError, ElapsedStages, STAGE_STATUSES
from seedbridge.campaign import BudgetSpec, CampaignRecord, CampaignSpec


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def budget(total=10):
    return BudgetSpec(total, 3, 3, 1, 1, 2, 0.5)


def spec(arm="symbolic_augment"):
    return CampaignSpec("phase_counter", arm, 1, 7, 20, budget())


def test_stage_timing_records_success_failure_and_nonoverlap():
    clock = FakeClock()
    ledger = BudgetLedger(10, clock=clock)
    with ledger.stage("build", kind="common") as stage:
        clock.advance(2)
        stage.finish("completed")
        with pytest.raises(RuntimeError, match="already active"):
            with ledger.stage("nested", kind="invalid"):
                pass
    with pytest.raises(ValueError, match="bad input"):
        with ledger.stage("selection", kind="prefix"):
            clock.advance(1)
            raise ValueError("bad input")
    assert [item["status"] for item in ledger.records] == ["completed", "tool_error"]
    assert [item["elapsed_seconds"] for item in ledger.records] == [2, 1]
    assert ledger.summary()["stage_elapsed_seconds"] == 3


@pytest.mark.parametrize("status", sorted(STAGE_STATUSES - {"running"}))
def test_all_declared_stage_outcomes_are_persisted(status):
    clock = FakeClock()
    ledger = BudgetLedger(10, clock=clock)
    with ledger.stage("augmentation", kind="augmentation") as stage:
        clock.advance(0.25)
        stage.finish(status, "classified outcome")
    assert ledger.records[0]["status"] == status
    assert ledger.records[0]["reason"] == "classified outcome"


def test_timeout_is_bounded_by_total_budget_and_reserve():
    clock = FakeClock()
    ledger = BudgetLedger(10, clock=clock)
    assert ledger.timeout_for(20, reserve_seconds=3) == 7
    clock.advance(8)
    with pytest.raises(CampaignDeadlineError):
        ledger.timeout_for(1, reserve_seconds=2)
    clock.advance(2)
    with pytest.raises(CampaignDeadlineError):
        with ledger.stage("continuation", kind="native"):
            pass
    assert ledger.records[-1]["status"] == "campaign_deadline"
    assert ledger.records[-1]["attempted"] is False


def test_common_work_is_logically_precharged_to_each_arm():
    clock = FakeClock()
    ledger = BudgetLedger(10, initial_charge_seconds=3, clock=clock)
    assert ledger.remaining_seconds == 7
    assert ledger.records[0]["logical_precharge"] is True
    clock.advance(2)
    summary = ledger.summary()
    assert summary["charged_wall_seconds"] == 5
    assert summary["stage_elapsed_seconds"] == 3
    assert summary["unattributed_wall_seconds"] == 2


def test_ledger_can_freeze_online_charge_before_offline_work():
    clock = FakeClock()
    ledger = BudgetLedger(10, clock=clock)
    with ledger.stage("online", kind="native"):
        clock.advance(3)
    charged_end = ledger.elapsed_seconds
    clock.advance(4)
    summary = ledger.summary(charged_end_seconds=charged_end)
    assert summary["charged_wall_seconds"] == pytest.approx(3)
    assert summary["remaining_seconds"] == pytest.approx(7)
    assert summary["deadline_reached"] is False


def test_result_finishing_after_deadline_is_saved_but_not_completed_on_budget():
    clock = FakeClock()
    ledger = BudgetLedger(3, cleanup_tolerance_seconds=1, clock=clock)
    with ledger.stage("native", kind="continuation"):
        clock.advance(3.5)
    event = ledger.records[0]
    assert event["status"] == "campaign_deadline"
    assert event["after_deadline"] is True
    assert event["after_deadline_by_seconds"] == 0.5
    assert event["within_cleanup_tolerance"] is True


def test_elapsed_stage_records_exception_in_finally():
    clock = FakeClock()
    target = {}
    recorder = ElapsedStages(target, clock=clock)
    with pytest.raises(RuntimeError):
        with recorder.measure("compile"):
            clock.advance(1.25)
            raise RuntimeError("compiler failed")
    assert target == {"compile": 1.25}


@pytest.mark.parametrize("arm", ["native_resume", "concrete_augment", "symbolic_augment"])
def test_campaign_schema_keeps_outcomes_independent(arm):
    record = CampaignRecord(spec(arm))
    assert record.goal_reached is False
    assert record.execution_status == "pending"
    assert record.evaluation_valid is False
    expected = "not_applicable" if arm == "native_resume" else "pending"
    assert record.augmentation_status == expected
    restored = CampaignSpec.from_dict(record.spec.to_dict())
    assert restored == record.spec


@pytest.mark.parametrize("change", [
    {"worker_count": 2}, {"call_value": "1"}, {"augmentation_rounds": 2},
    {"max_steps": 5}, {"max_prefixes": 5}, {"arm": "unknown"},
])
def test_campaign_spec_rejects_out_of_scope_configuration(change):
    values = spec().to_dict()
    values.update(change)
    values["budget"] = BudgetSpec(**values["budget"])
    with pytest.raises(ValueError):
        CampaignSpec(**values)


def test_record_persists_budget_and_stage_evidence(tmp_path):
    clock = FakeClock()
    ledger = BudgetLedger(10, clock=clock)
    record = CampaignRecord(spec())
    with ledger.stage("warmup", kind="common"):
        clock.advance(2)
    record.execution_status = "completed"
    record.augmentation_status = "no_candidate"
    record.lineage_status = "unverified"
    record.evaluation_valid = True
    record.finalize(ledger)
    path = tmp_path / "campaign.json"
    record.save(path)
    import json
    saved = json.loads(path.read_text())
    assert saved["execution_status"] == "completed"
    assert saved["augmentation_status"] == "no_candidate"
    assert saved["goal_reached"] is False
    assert saved["budget"]["charged_wall_seconds"] == 2
    assert saved["stages"][0]["name"] == "warmup"
