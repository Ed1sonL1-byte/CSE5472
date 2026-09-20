"""Stage 3 common-block and profile execution using the existing bridge core."""

from __future__ import annotations

import hashlib
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
import uuid

from .augmentation import concrete_augment, save_augmentation, symbolic_augment
from .budget import BudgetLedger, CampaignDeadlineError
from .build import assert_medusa_build, build_manifest
from .cache import copy_isolated_workspace, create_fixture_base, storage_preflight, tree_manifest
from .config import ROOT, get_scenario
from .doctor import inspect_toolchain
from .io import file_hash, read_json, write_json
from .medusa import build_fixture, campaign
from .metrics import save_segmented_metrics, segmented_metrics
from .process import EvidenceMismatchError, ToolExecutionError
from .study import StudyProfile, StudySlot, StudySpec, load_study_spec
from .trace import select_prefixes


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=ROOT, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip()


def _source_paths() -> list[Path]:
    paths: set[Path] = set()
    for pattern in (
        "src/seedbridge/*.py", "adapters/medusa/*.go", "adapters/medusa/go.mod",
        "adapters/medusa/go.sum", "adapters/medusa/patches/*.patch", "fixtures/*/src/*.sol",
        "fixtures/*/foundry.toml", "configs/stage3-*.json", "pyproject.toml", "uv.lock",
        ".python-version",
    ):
        paths.update(path for path in ROOT.glob(pattern) if path.is_file())
    return sorted(paths)


def snapshot_execution_source(destination: Path) -> dict:
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("execution source snapshot destination must be new")
    rows = []
    combined = hashlib.sha256()
    for source in _source_paths():
        relative = source.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        digest = file_hash(target)
        rows.append({"path": relative.as_posix(), "bytes": target.stat().st_size, "sha256": digest})
        combined.update(relative.as_posix().encode())
        combined.update(b"\0")
        combined.update(digest.encode())
        combined.update(b"\n")
    manifest = {
        "schema_version": 1,
        "git_head": _git("rev-parse", "HEAD"),
        "git_status": _git("status", "--porcelain=v1"),
        "file_count": len(rows),
        "content_sha256": combined.hexdigest(),
        "files": rows,
    }
    write_json(destination / "source-manifest.json", manifest)
    return manifest


def current_execution_source() -> dict:
    rows = []
    combined = hashlib.sha256()
    for source in _source_paths():
        relative = source.relative_to(ROOT).as_posix()
        digest = file_hash(source)
        rows.append({"path": relative, "bytes": source.stat().st_size, "sha256": digest})
        combined.update(relative.encode())
        combined.update(b"\0")
        combined.update(digest.encode())
        combined.update(b"\n")
    return {"file_count": len(rows), "content_sha256": combined.hexdigest(), "files": rows}


def study_manifest(config_path: Path, spec: StudySpec, source: dict,
                   storage: dict, toolchain: dict) -> dict:
    patch = ROOT / "adapters/medusa/patches/medusa-v1.5.1-lineage.patch"
    adapter = ROOT / ".bin/medusa-adapter"
    return {
        "schema_version": 1,
        "study_id": spec.study_id,
        "run_id": uuid.uuid4().hex,
        "status": "running",
        "config_path": str(Path(config_path).resolve()),
        "config_sha256": file_hash(config_path),
        "plan": spec.plan(),
        "execution_source": source,
        "toolchain": toolchain,
        "host": {"hostname": socket.gethostname(), "platform": platform.platform(),
                 "python": platform.python_version()},
        "medusa": {
            "version": "v1.5.1",
            "adapter_sha256": file_hash(adapter),
            "lineage_patch_sha256": file_hash(patch),
        },
        "storage_preflight": storage,
        "randomness_boundary": {
            "controlled": ["worker seed", "block order", "profile order", "corpus filenames",
                           "concrete random samples"],
            "uncontrolled": ["Medusa corpus chooser clock-seeded RNG",
                             "Medusa mutation strategy chooser clock-seeded RNG"],
        },
        "cache_protocol": (
            "one isolated built cache base per fixture/repeat; every profile receives a charged "
            "byte-for-byte copy and cannot publish new cache artifacts to another profile"
        ),
        "completed_blocks": [],
        "failed_block_attempts": [],
    }


def prepare_study_common(spec: StudySpec, fixture_id: str, repeat_id: int,
                         directory: Path, toolchain: dict) -> dict:
    started = time.monotonic()
    scenario = get_scenario(fixture_id)
    directory.mkdir(parents=True, exist_ok=False)
    base_project = directory / "cache-base/project"
    source_copy = create_fixture_base(fixture_id, base_project)
    build_command = build_fixture(
        fixture_id, directory / "build", spec.common_limit_seconds, project=base_project)
    build = build_manifest(
        base_project, scenario.contract, directory / "build", spec.common_limit_seconds)
    corpus = directory / "warmup/corpus"
    warmup = campaign(
        fixture_id, directory / "warmup", seed=spec.seed(fixture_id, repeat_id),
        tests=spec.warmup_sequences, fuzz_timeout=spec.common_limit_seconds,
        process_timeout=spec.common_limit_seconds + 2.0, corpus=corpus,
        project=base_project,
    )
    assert_medusa_build(build, warmup)
    prefixes, rejected = select_prefixes(warmup, spec.max_prefixes, fixture_id)
    write_json(directory / "prefix-pool.json", {"selected": prefixes, "rejected": rejected})
    cache = tree_manifest(base_project)
    elapsed = time.monotonic() - started
    result = {
        "schema_version": 1,
        "common_block_id": f"{fixture_id}/repeat-{repeat_id:02d}",
        "fixture_id": fixture_id,
        "repeat_id": repeat_id,
        "seed": spec.seed(fixture_id, repeat_id),
        "elapsed_seconds": elapsed,
        "within_common_limit": elapsed <= spec.common_limit_seconds,
        "source_copy": source_copy,
        "build_command": build_command,
        "build": build,
        "cache_base_path": str(base_project),
        "cache_manifest": cache,
        "warmup_path": warmup["output_path"],
        "corpus_path": str(corpus),
        "corpus_manifest": tree_manifest(corpus),
        "prefix_pool_path": str(directory / "prefix-pool.json"),
        "selected_prefixes": len(prefixes),
        "warmup_goal_reached": any(
            step.get("goal") is True
            for sequence in warmup.get("sequences", []) for step in sequence.get("steps", [])
        ),
        "toolchain": toolchain,
    }
    write_json(directory / "common.json", result)
    return {**result, "warmup": warmup, "prefixes": prefixes}


def _copy_accepted(augmentation: dict, corpus: Path) -> list[str]:
    destination = corpus / "call_sequences"
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, candidate in enumerate(augmentation.get("accepted", [])):
        target = destination / f"zz-augmentation-{index:02d}.json"
        shutil.copy2(candidate["accepted_native_path"], target)
        paths.append(str(target))
    return paths


def _slot_spec(spec: StudySpec, slot: StudySlot, profile: StudyProfile) -> dict:
    return {
        **slot.to_dict(),
        "schema_version": 1,
        "warmup_sequences": spec.warmup_sequences,
        "continuation_sequence_safety_limit": spec.continuation_sequence_safety_limit,
        "augmentation_limit_seconds": profile.augmentation_limit_seconds,
        "startup_reserve_seconds": profile.startup_reserve_seconds,
        "continuation_reserve_seconds": profile.continuation_reserve_seconds,
        "cleanup_tolerance_seconds": profile.cleanup_tolerance_seconds,
        "max_steps": 4,
        "max_prefixes": spec.max_prefixes,
        "max_candidates": spec.max_candidates,
        "concrete_attempts_per_prefix": spec.concrete_attempts_per_prefix,
        "worker_count": 1,
        "call_value": "0",
        "augmentation_rounds": 1,
    }


def project_native_to_budget(native: dict, *, native_stage_start: float,
                             budget_deadline: float) -> tuple[dict, dict]:
    """Map adapter-relative events to one ledger and exclude post-deadline metrics."""
    mapping = native.get("completion_timing")
    if not isinstance(mapping, dict):
        raise EvidenceMismatchError("native timing map is missing", status="evidence_error")
    search_start = native_stage_start + float(mapping["search_started"])
    sequences = native.get("sequences")
    lineage = native.get("lineage")
    if not isinstance(sequences, list) or not isinstance(lineage, list):
        raise EvidenceMismatchError("native sequence evidence is missing", status="evidence_error")
    by_index = {sequence.get("sequence_index"): sequence for sequence in sequences}
    if len(by_index) != len(sequences) or None in by_index:
        raise EvidenceMismatchError("native sequence indices are not unique", status="evidence_error")
    in_budget_lineage = []
    in_budget_sequences = []
    after_deadline = []
    for event in lineage:
        index = event.get("sequence_index")
        if index not in by_index:
            raise EvidenceMismatchError(
                "native lineage refers to an absent sequence", status="evidence_error")
        offset = search_start + float(event["completed_offset_seconds"])
        event["charged_offset_seconds"] = offset
        event["after_deadline"] = offset > budget_deadline
        sequence = by_index[index]
        sequence["charged_offset_seconds"] = offset
        sequence["after_deadline"] = event["after_deadline"]
        if event["after_deadline"]:
            after_deadline.append(index)
        else:
            in_budget_lineage.append(event)
            in_budget_sequences.append(sequence)
    if len(lineage) != len(sequences):
        raise EvidenceMismatchError(
            "native lineage and complete sequences are not one-to-one", status="evidence_error")
    timing = {
        "basis": "adapter offsets mapped from the charged native-stage start",
        "budget_deadline": budget_deadline,
        "native_stage_started": native_stage_start,
        "search_started": search_start,
        "search_stopped": native_stage_start + float(mapping["search_stopped"]),
        "last_observed_event": native_stage_start + float(mapping["last_observed_event"]),
        "metric_observation_end": max(
            (float(event["charged_offset_seconds"]) for event in in_budget_lineage),
            default=search_start,
        ),
        "event_stream_finished": native_stage_start + float(mapping["event_stream_finished"]),
        "evidence_flush_finished": native_stage_start + float(mapping["evidence_flush_finished"]),
        "after_deadline_sequence_indices": after_deadline,
    }
    projected = {
        **native,
        "sequences": in_budget_sequences,
        "lineage": in_budget_lineage,
        "completed_sequences": len(in_budget_sequences),
    }
    return projected, timing


def run_study_slot(spec: StudySpec, slot: StudySlot, common: dict,
                   directory: Path) -> dict:
    profile = spec.profile(slot.profile_id)
    directory.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 1,
        "spec": _slot_spec(spec, slot, profile),
        "execution_status": "pending",
        "augmentation_status": "not_applicable" if slot.arm == "native_resume" else "pending",
        "lineage_status": "pending",
        "evidence_status": "pending",
        "goal_reached": False,
        "evaluation_valid": False,
        "failure": None,
        "artifacts": {},
        "outcomes": {},
        "online_timing": {},
    }
    ledger = BudgetLedger(
        profile.total_budget_seconds,
        cleanup_tolerance_seconds=profile.cleanup_tolerance_seconds,
        initial_charge_seconds=common["elapsed_seconds"],
    )
    augmentation: dict = {"status": "not_applicable", "attempts": [], "accepted": []}
    native: dict | None = None
    charged_end: float | None = None
    try:
        with ledger.stage("input_and_cache_prepare", kind="preparation"):
            workspace = directory / "workspace/project"
            cache_copy = copy_isolated_workspace(Path(common["cache_base_path"]), workspace)
            corpus = directory / "corpus"
            corpus_started = time.monotonic()
            shutil.copytree(common["corpus_path"], corpus)
            corpus_copy_seconds = time.monotonic() - corpus_started
            corpus_manifest = tree_manifest(corpus)
            record["artifacts"].update({
                "workspace": str(workspace),
                "cache_copy": cache_copy,
                "corpus_copy": {
                    "elapsed_seconds": corpus_copy_seconds,
                    "source_content_sha256": common["corpus_manifest"]["content_sha256"],
                    "destination_content_sha256": corpus_manifest["content_sha256"],
                    "file_count": corpus_manifest["file_count"],
                    "byte_count": corpus_manifest["byte_count"],
                },
            })
            if corpus_manifest["content_sha256"] != common["corpus_manifest"]["content_sha256"]:
                raise EvidenceMismatchError("profile corpus copy differs from common input")

        with ledger.stage("prefix_pool", kind="prefix") as stage:
            prefixes = list(common["prefixes"])
            write_json(directory / "prefix-pool.json", {"selected": prefixes})
            if not prefixes and slot.arm != "native_resume":
                stage.finish("no_eligible_prefix", "common warmup produced no eligible goal=false prefix")

        if slot.arm == "native_resume":
            ledger.record_skipped(
                "augmentation", kind="augmentation", status="skipped",
                reason="native_resume performs no augmentation")
        elif not prefixes:
            augmentation = {"status": "no_eligible_prefix", "attempts": [], "accepted": []}
            record["augmentation_status"] = "no_eligible_prefix"
            ledger.record_skipped(
                "augmentation", kind="augmentation", status="no_eligible_prefix",
                reason="common prefix pool is empty")
        else:
            with ledger.stage("augmentation", kind="augmentation") as stage:
                available = ledger.timeout_for(
                    profile.augmentation_limit_seconds,
                    reserve_seconds=profile.startup_reserve_seconds + profile.continuation_reserve_seconds,
                )
                try:
                    if slot.arm == "concrete_augment":
                        augmentation = concrete_augment(
                            slot.fixture_id, prefixes, common["warmup"], directory / "augmentation",
                            seed=slot.seed, attempts_per_prefix=spec.concrete_attempts_per_prefix,
                            max_candidates=spec.max_candidates, timeout=available,
                            boundary_values=spec.boundary_values, project=workspace,
                        )
                    else:
                        goal_limit = profile.goal_invocation_limit_seconds
                        if goal_limit is None:
                            raise ValueError("symbolic study profile has no goal invocation limit")
                        augmentation = symbolic_augment(
                            slot.fixture_id, prefixes, common["warmup"], directory / "augmentation",
                            seed=slot.seed, max_candidates=spec.max_candidates,
                            prefix_query_timeout=profile.prefix_check_limit_seconds,
                            goal_query_timeout=goal_limit,
                            process_timeout=available, total_timeout=available,
                            solver=common["toolchain"]["tools"]["z3"]["path"],
                            executable=common["toolchain"]["tools"]["halmos"]["path"],
                            baseline_build=common["build"], project=workspace,
                        )
                except ToolExecutionError as error:
                    if error.status != "timeout":
                        raise
                    augmentation = {
                        "status": "timeout", "reason": str(error),
                        "attempts": [], "accepted": [],
                    }
                save_augmentation(directory / "augmentation", augmentation)
                record["augmentation_status"] = augmentation["status"]
                if augmentation["status"] in {
                    "no_candidate", "timeout", "invalid_model", "replay_mismatch",
                }:
                    stage.finish(augmentation["status"], "augmentation produced no accepted seed")
        with ledger.stage("seed_import", kind="import"):
            record["artifacts"]["accepted_seed_paths"] = _copy_accepted(augmentation, corpus)

        with ledger.stage("native_startup_and_continuation", kind="native") as native_stage:
            remaining = ledger.remaining_seconds
            setup_margin = profile.startup_reserve_seconds + profile.cleanup_tolerance_seconds + 0.25
            fuzz_timeout = remaining - setup_margin
            if fuzz_timeout <= 0:
                raise CampaignDeadlineError("no budget remains for native continuation")
            native = campaign(
                slot.fixture_id, directory / "native", seed=slot.seed,
                tests=spec.continuation_sequence_safety_limit,
                fuzz_timeout=fuzz_timeout,
                process_timeout=remaining + profile.cleanup_tolerance_seconds,
                corpus=corpus, compact=True, project=workspace,
            )
        with ledger.stage("online_evidence_validation", kind="evidence"):
            if native.get("stop_reason") != "time_limit":
                raise EvidenceMismatchError(
                    f"native campaign stopped for {native.get('stop_reason')}, not the time protocol",
                    status="evidence_error",
                )
            continuation = [event for event in native["lineage"]
                            if event["kind"] in {"new_sequence", "mutation"}]
            mutations = [event for event in continuation if event["kind"] == "mutation"]
            lineage_ok = (
                len(native["lineage"]) == native["completed_sequences"]
                and bool(continuation)
                and all(event["parents_resolved"] for event in mutations)
            )
            record["lineage_status"] = "verified" if lineage_ok else "unverified"
            if not lineage_ok:
                raise EvidenceMismatchError(
                    "compact lineage is incomplete or unresolved", status="evidence_error")
            stage_start = float(native_stage.record["started_offset_seconds"])
            metric_native, record["online_timing"] = project_native_to_budget(
                native, native_stage_start=stage_start,
                budget_deadline=profile.total_budget_seconds,
            )
        charged_end = ledger.elapsed_seconds
        metrics = segmented_metrics(slot.fixture_id, common["warmup"], metric_native)
        save_segmented_metrics(directory, metrics)
        record["goal_reached"] = any(metrics["goal_reached"].values())
        record["execution_status"] = "completed"
        record["evidence_status"] = "verified"
        record["outcomes"] = {
            "warmup_goal_reached": common["warmup_goal_reached"],
            "augmentation_accepted": len(augmentation.get("accepted", [])),
            "completed_sequences": native["completed_sequences"],
            "metric_sequences": metric_native["completed_sequences"],
            "after_deadline_sequences": len(
                record["online_timing"]["after_deadline_sequence_indices"]),
            "partial_sequences": len(native.get("partial_sequences", [])),
            "startup_replays": native["startup_replays"],
            "new_sequences": native["new_sequences"],
            "mutation_sequences": native["mutation_sequences"],
            "stop_reason": native["stop_reason"],
            "native_status": native["status"],
            "native_timing_seconds": native.get("native_timing_seconds", {}),
            "dimension_deltas": metrics["dimensions"],
        }
        record["artifacts"].update({
            "common_path": str(Path(common["warmup_path"]).parents[1] / "common.json"),
            "native_report": native["output_path"],
            "event_stream": native["compact_events"]["path"],
            "completion_timing": native["completion_path"],
            "metrics": str(directory / "metrics.json"),
            "workspace_final_manifest": tree_manifest(workspace),
        })
    except CampaignDeadlineError as error:
        record["execution_status"] = "campaign_deadline"
        record["failure"] = {"classification": "campaign_deadline", "reason": str(error)}
    except ToolExecutionError as error:
        record["execution_status"] = "tool_error"
        record["failure"] = {"classification": error.status, "reason": str(error)}
    except EvidenceMismatchError as error:
        record["execution_status"] = "evidence_error"
        record["failure"] = {"classification": error.status, "reason": str(error)}
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        record["execution_status"] = "tool_error"
        record["failure"] = {
            "classification": "tool_error", "reason": f"{type(error).__name__}: {error}"}
    finally:
        if charged_end is None:
            charged_end = ledger.elapsed_seconds
        record["stages"] = list(ledger.records)
        record["budget"] = ledger.summary(charged_end_seconds=charged_end)
        record["online_timing"]["charged_end"] = record["budget"]["charged_wall_seconds"]
        record["online_timing"]["unused_budget_seconds"] = record["budget"]["remaining_seconds"]
        record["evaluation_valid"] = (
            record["execution_status"] == "completed"
            and record["lineage_status"] == "verified"
            and record["evidence_status"] == "verified"
            and common["within_common_limit"] is True
            and not any(stage.get("after_deadline") for stage in ledger.records)
        )
        write_json(directory / "campaign.json", record)
    return record


def run_study(config_path: Path, output: Path) -> dict:
    spec = load_study_spec(config_path)
    output = Path(output).resolve()
    return _run_study(spec, Path(config_path).resolve(), output, resume=False)


def resume_study(config_path: Path, output: Path) -> dict:
    spec = load_study_spec(config_path)
    output = Path(output).resolve()
    return _run_study(spec, Path(config_path).resolve(), output, resume=True)


def _run_study(spec: StudySpec, config_path: Path, output: Path, *, resume: bool) -> dict:
    if output.exists() != resume:
        expected = "existing" if resume else "new"
        raise ValueError(f"study output directory must be {expected}")
    storage = storage_preflight(
        output, minimum_free_bytes=spec.storage_min_free_bytes,
        maximum_study_bytes=spec.storage_max_study_bytes,
    )
    if not storage["ok"]:
        raise RuntimeError(storage["reason"])
    toolchain = inspect_toolchain()
    if not toolchain["ok"]:
        raise RuntimeError("toolchain preflight failed")
    if resume:
        manifest = read_json(output / "manifest.json")
        if (manifest.get("study_id") != spec.study_id
                or manifest.get("config_sha256") != file_hash(config_path)
                or file_hash(output / "frozen-config.json") != file_hash(config_path)
                or manifest.get("execution_source", {}).get("content_sha256")
                != current_execution_source()["content_sha256"]
                or manifest.get("medusa", {}).get("adapter_sha256")
                != file_hash(ROOT / ".bin/medusa-adapter")):
            raise RuntimeError("resume inputs differ from the frozen study execution version")
        completed_ids = {
            block["common_block_id"] for block in manifest.get("completed_blocks", [])
        }
    else:
        output.mkdir(parents=True)
        shutil.copy2(config_path, output / "frozen-config.json")
        source = snapshot_execution_source(output / "execution-source")
        manifest = study_manifest(config_path, spec, source, storage, toolchain)
        manifest["frozen_config_path"] = str(output / "frozen-config.json")
        manifest["attempt_elapsed_seconds"] = []
        completed_ids = set()
        write_json(output / "manifest.json", manifest)
    started = time.monotonic()
    stopped_early = False
    for fixture_id in spec.fixtures:
        for repeat_id in spec.repeats:
            common_block_id = f"{fixture_id}/repeat-{repeat_id:02d}"
            if common_block_id in completed_ids:
                continue
            block = output / "blocks" / fixture_id / f"repeat-{repeat_id:02d}"
            if block.exists():
                failed = (output / "failed-block-attempts" / fixture_id /
                          f"repeat-{repeat_id:02d}" / f"attempt-{uuid.uuid4().hex[:12]}")
                failed.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(block), str(failed))
                manifest["failed_block_attempts"].append({
                    "common_block_id": common_block_id,
                    "reason": "incomplete block found at resume boundary",
                    "path": str(failed),
                })
            common = prepare_study_common(
                spec, fixture_id, repeat_id, block / "common", toolchain)
            block_records = []
            for profile_id in spec.profile_orders[str(repeat_id)]:
                slot = next(slot for slot in spec.slots()
                            if slot.fixture_id == fixture_id and slot.repeat_id == repeat_id
                            and slot.profile_id == profile_id)
                record = run_study_slot(
                    spec, slot, common, block / "profiles" / profile_id)
                block_records.append(record)
            block_valid = sum(record["evaluation_valid"] for record in block_records)
            block_result = {
                "common_block_id": common_block_id,
                "valid_profiles": block_valid,
                "profile_count": len(spec.profiles),
                "common_cache_sha256": common["cache_manifest"]["content_sha256"],
                "common_corpus_sha256": common["corpus_manifest"]["content_sha256"],
            }
            if block_valid == len(spec.profiles):
                manifest["completed_blocks"].append(block_result)
                completed_ids.add(common_block_id)
            else:
                block_result["reason"] = "one or more profiles were evaluation-invalid"
                block_result["path"] = str(block)
                manifest["failed_block_attempts"].append(block_result)
                stopped_early = True
            write_json(output / "manifest.json", manifest)
            if stopped_early:
                break
        if stopped_early:
            break
    attempt_elapsed = time.monotonic() - started
    manifest.setdefault("attempt_elapsed_seconds", []).append(attempt_elapsed)
    manifest["physical_elapsed_seconds"] = sum(manifest["attempt_elapsed_seconds"])
    records = [
        read_json(path)
        for path in sorted(output.glob("blocks/*/repeat-*/profiles/*/campaign.json"))
        if any(block_id in path.as_posix() for block_id in completed_ids)
    ]
    manifest["result_count"] = len(records)
    manifest["evaluation_valid_count"] = sum(record["evaluation_valid"] for record in records)
    manifest["status"] = (
        "complete" if manifest["evaluation_valid_count"] == len(spec.slots()) else "incomplete")
    write_json(output / "manifest.json", manifest)
    return manifest
