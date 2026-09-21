# SeedBridge — Symbolic Seed Augmentation

SeedBridge is a local CSE 5472 project prototype that connects Medusa, Halmos, and Foundry. It takes a concrete call prefix that Medusa actually executed, asks Halmos to solve one argument for the next call, validates the candidate against a fresh deployment, converts the sequence back to Medusa's native format, and observes its execution and mutation lineage.

The repository contains three completed stages:

- Stage 1 validates the cross-tool workflow on `PhaseCounter` and `BoundedLedger`.
- Stage 2 adds `RangeGate` and `WorkflowGate`, restores Medusa's default generation and mutation behavior, and compares native, concrete-augmentation, and symbolic-augmentation strategies under the same wall-clock budget. All 60 formal records passed the independent audit.
- Stage 3 adds versioned study specifications, precise observation boundaries, isolated caches, compact raw event streams, independent offline auditing, and reproducible archives. All 320 formal records passed the independent audit.

Public, path-sanitized results are available in the [Stage 2 evidence bundle](evidence/stage2/INDEX.md) and [Stage 3 evidence bundle](evidence/stage3/INDEX.md).

Goal reachability is not a vulnerability finding. The four fixtures are repository-owned teaching state machines, and their results do not establish performance on third-party contracts.

## Workflow

```text
Medusa execution and native corpus
  → select a concrete prefix whose target is still false
  → independently replay the prefix with Halmos
  → solve one uint256 argument for the final call
  → concretely replay the full sequence on a fresh deployment
  → export the sequence through the native Medusa codec
  → restart Medusa and confirm seed execution and mutation admission
  → continue default generation and mutation while recording real lineage
  → independently audit raw evidence and render reports
```

The engine does not hard-code target solutions. Fixture metadata defines the supported calls, finite-state projection, and goal observer; Medusa supplies executed prefixes, Halmos supplies candidate values, and a separate concrete replay decides whether a candidate is accepted.

## Supported scope

- Four built-in fixtures: `phase_counter`, `bounded_ledger`, `range_gate`, and `workflow_gate`.
- One fixed deployer and actor per fixture.
- Zero transaction value.
- One symbolic `uint256` argument.
- Concrete prefixes of one to three successful calls.
- Complete sequences of at most four calls.
- One Medusa worker and one augmentation batch.
- A declared finite-state projection rather than complete EVM world-state equivalence.

| Fixture | Purpose |
| --- | --- |
| `PhaseCounter` | A narrow integer condition that is difficult for ordinary concrete input generation. |
| `BoundedLedger` | An independent state machine and invariant used to verify the shared pipeline. |
| `RangeGate` | A broad condition used to measure augmentation overhead when concrete exploration is already effective. |
| `WorkflowGate` | A staged condition with post-goal behavior used to expose the tradeoff between augmentation and continuation time. |

The fixtures contain no real funds, external calls, or attack payloads. Arbitrary external contracts, complex ABI values, multiple actors, nonzero value, and multi-step symbolic suffixes are outside the implemented scope.

## Pinned environment

Run all commands from the repository root. Install `uv`, Go 1.26.4, and Forge 1.3.2 first. Python is pinned to 3.12 by `.python-version`.

| Component | Version or source |
| --- | --- |
| Python | 3.12 in the project `.venv` |
| Go | 1.26.4 with `GOTOOLCHAIN=local` for the adapter build |
| Forge | 1.3.2 |
| solc | 0.8.36 through an explicit binary path |
| Halmos | 0.3.3 from `uv.lock` |
| crytic-compile | 0.3.11 from `uv.lock` |
| Z3 | 4.12.6 from the locked project environment |
| Medusa | v1.5.1 as a Go module dependency compiled into `.bin/medusa-adapter` |

Bootstrap and inspect the toolchain:

```sh
./scripts/bootstrap.sh
./seedbridge doctor
```

Bootstrap performs a frozen `uv` sync, installs solc 0.8.36 when necessary, verifies and applies the minimal pinned Medusa lineage patch, builds the Go adapter, writes the local toolchain record, and compiles all four fixtures. It does not install Go or Forge and does not switch the global solc selection.

Set an explicit compiler path before bootstrap when solc is installed elsewhere:

```sh
export SEEDBRIDGE_SOLC="/absolute/path/to/solc-0.8.36"
./scripts/bootstrap.sh
```

Use the repository's `./seedbridge` launcher. It selects the locked Python environment and sets `PYTHONPATH=src`.

## Run one complete fixture workflow

```sh
./seedbridge run phase_counter
./seedbridge run bounded_ledger
./seedbridge run range_gate
./seedbridge run workflow_gate
```

Each command creates an independent directory under `runs/` and prints the path to `report.md`. A caller-provided output directory must not already exist:

```sh
./seedbridge run phase_counter --seed 1 --output runs/phase-counter-review
```

Useful controls include `--seed`, `--warmup-tests`, `--max-prefixes`, `--process-timeout`, `--total-solve-timeout`, and `--output`. Use `./seedbridge run --help` for current defaults.

Regenerate a report from stored data without rerunning the tools:

```sh
./seedbridge report runs/phase-counter-review
```

## Stage 2 benchmark

The frozen configuration is `configs/stage2-benchmark.json`.

```sh
./seedbridge campaign phase_counter symbolic_augment \
  --repeat 1 --output runs/campaign-review

./seedbridge benchmark \
  --config configs/stage2-benchmark.json \
  --output runs/stage2-review

./seedbridge benchmark-report runs/stage2-review

uv run --frozen python scripts/audit-stage2.py \
  runs/stage2-review --output runs/stage2-review/audit.json

uv run --frozen python scripts/build-stage2-evidence.py
```

The three arms are `native_resume`, `concrete_augment`, and `symbolic_augment`. Each `(fixture, repeat)` performs one shared warmup, and every arm starts from its own copy of the same corpus. Shared work is charged to each arm's logical budget. Misses are right-censored at the actual observed end; the configured eight seconds remain a separate budget ceiling.

Raw runs are ignored by Git. The public extract is stored in `evidence/stage2/`.

## Stage 3 study

The frozen formal configuration is `configs/stage3-study.json`. It expands to 320 distinct slots in 40 shared-warmup blocks.

Inspect the matrix without running native tools:

```sh
./seedbridge study-plan --config configs/stage3-study.json
```

Run a fresh study in a new output directory:

```sh
./seedbridge study \
  --config configs/stage3-study.json \
  --output runs/stage3-review
```

A study can resume only at a verified complete common-block boundary. Resume validates the frozen configuration, source snapshot, and adapter hash:

```sh
./seedbridge study --resume \
  --config configs/stage3-study.json \
  --output runs/stage3-review
```

Independently audit compact raw evidence and render reports:

```sh
./seedbridge study-audit runs/stage3-review \
  --output runs/stage3-review/derived/audit.json

./seedbridge study-report runs/stage3-review \
  --output runs/stage3-review/derived
```

Create and verify a self-contained archive:

```sh
./seedbridge study-export runs/stage3-review \
  --output artifacts/stage3-review.tar.gz

./seedbridge study-verify-archive artifacts/stage3-review.tar.gz \
  --output runs/stage3-review-offline-verify
```

The archive contains the frozen configuration and source, compact raw events, accepted native seeds, model and replay evidence, derived reports, per-file checksums, and a standard-library rebuild script.

## Formal Stage 3 result

- 320/320 evaluation-valid slots in 40/40 complete blocks.
- 243 goal-hit slots.
- 791,282 complete sequences.
- 553,708 mutation events.
- 8-second aggregate hits: native 17/40, concrete 22/40, symbolic 39/40.
- 32-second aggregate hits: native 20/40, concrete 25/40, symbolic 40/40.
- The 0.50, 0.75, and 1.50 second symbolic goal-invocation profiles each reached 40/40 at the 32-second total budget.

The complete local archive is `artifacts/stage3-formal-v1.tar.gz`:

```text
bytes:   3358084381
sha256:  91bf6e5063a4d7644e0f84a1c8187480a35c66185e4f929d275384db6ad2ad25
files:   43482 archived study files
```

The 3.1 GB archive is intentionally ignored by Git. Its checksum, archive metadata, two-rebuild verification, all 320 observations, independent audit, summary, and charts are published under `evidence/stage3/`.

## Randomness and comparison boundaries

Stage 1 uses Medusa's native new-sequence-only generator with one worker to reduce scheduling variability while validating the integration. This configuration is not equivalent to stock Medusa's default scheduling, so Stage 1 coverage and timing are not performance comparisons.

Stage 2 and Stage 3 use Medusa v1.5.1's default generation and mutation strategies. The pinned patch only exposes the generation identifier and real selected parent; it does not add random choices or change weights.

The worker seed, block order, profile order, corpus names, and concrete random samples are controlled. Medusa's corpus chooser and mutation-strategy chooser still use disclosed clock-seeded randomness. Equal warmups therefore do not imply identical continuation trajectories, and the formal slots are paired observations rather than fully independent samples.

## Evidence classification

A complete Stage 1 acceptance requires all of the following:

1. Native sequences round-trip losslessly, and observation does not change state, outcomes, coverage feedback, or admission.
2. The selected prefix came from a real Medusa execution and replays with the same actor, context, outcomes, and state projection.
3. Halmos returns a valid typed model for the expected target test, and a fresh concrete deployment confirms the target changes from false to true.
4. The candidate is not a duplicate and is actually executed by restarted Medusa.
5. Independent evidence shows that the completed sequence entered the mutation candidate set.

Stage 3 separates valid negative outcomes such as `no_eligible_prefix`, `no_candidate`, bounded augmentation timeout, and native continuation miss from tool, state, and evidence errors. Tool and evidence errors can never be counted as evaluation-valid records.

## Tests

Run the Python unit suite:

```sh
uv run --frozen pytest tests/unit -q
```

Run the complete suite, including real-tool integration tests:

```sh
SEEDBRIDGE_INTEGRATION=1 uv run --frozen pytest -q
```

Run Go adapter tests:

```sh
cd adapters/medusa
GOTOOLCHAIN=local go test -mod=readonly ./...
```

Audit the saved Stage 3 protocol evidence and verify public evidence checksums:

```sh
./scripts/audit-stage3-protocol.py
./seedbridge study-audit runs/stage3-formal-02
./scripts/build-stage3-evidence.py
(cd evidence/stage3 && shasum -a 256 -c checksums.sha256)
```

The latest completed validation recorded 156 passing unit tests, 163 passing tests with integration enabled, a passing Go adapter suite, 320/320 valid formal Stage 3 records, and a successful two-pass offline archive rebuild.

## Repository layout

| Path | Contents |
| --- | --- |
| `src/seedbridge/` | Python CLI, configuration, augmentation, budgets, compact records, studies, auditing, reporting, and archiving. |
| `adapters/medusa/` | Fixed-version Go codec, execution observer, compact writer, continuation support, and lineage integration. |
| `fixtures/` | Four local teaching contracts, Foundry configuration, and concrete tests. |
| `configs/stage2-benchmark.json` | Frozen Stage 2 matrix, budgets, order, and seeds. |
| `configs/stage3-study.json` | Frozen 320-slot Stage 3 matrix, budgets, query limits, order, and seeds. |
| `evidence/stage2/` | Path-sanitized Stage 2 summaries, mechanism evidence, audit, and checksums. |
| `evidence/stage3/` | All 320 observations, independent audit, summary, charts, protocol audit, and archive verification metadata. |
| `artifacts/` | Local archive documentation and tracked archive checksum files. |
| `scripts/` | Bootstrap, auditing, evidence conversion, snapshot, and evidence-bundle utilities. |
| `tests/` | Python unit and native integration tests. |
| `runs/` | Git-ignored raw executions and generated reports. |

SeedBridge is built on [Medusa](https://github.com/crytic/medusa), [Halmos](https://github.com/a16z/halmos), and [Foundry](https://github.com/foundry-rs/foundry). [Optik](https://github.com/crytic/optik) provides related prior practice in symbolic-execution-assisted fuzzing. This repository presents a constrained integration and evidence protocol rather than claiming hybrid fuzzing as a new method.
