# Stage 4 technical plan: safety property validation and controlled regression

Owner: Edison Li

## Scope and frozen boundary

Stage 4 adds one local integer-accounting case in flawed and repaired forms. Both versions have the same ABI, initial configuration, actor, zero call value, and independently computed safety property. The existing reachability fixtures, Stage 1–3 configurations, raw records, and published evidence remain unchanged. Prefixes contain one to three concrete calls; only one `uint256` argument in the final call is symbolic. No known regression input enters the experimental corpus or candidate generator.

The formal evaluation uses a single 32-second total budget, three arms (`native_resume`, `concrete_augment`, `symbolic_augment`), two versions, and repeats 1–10: 60 slots. The outcome is valid even if symbolic augmentation has no advantage. A tool or evidence failure is never a valid negative result.

The first formal attempt (`stage4-safety-formal-v1`) stopped after 45 valid slots when one native evidence-decoding stage exceeded the charged budget. Its raw records remain under `runs/stage4-formal-v1/`. The frozen v2 protocol reserves nine seconds within the same 32-second total budget for native setup, event decoding, and evidence work; all 60 v2 slots must be rerun from the start. This changes exposure time, so v1 and v2 observations must never be combined.

## P0 — Baseline and protocol

**Work:** Inspect the current repository and applicable agent instructions; record the existing CLI, adapter, harness, replay, budget, and audit interfaces. Define the Stage 4 status taxonomy and freeze points. Repair the adapter's repository-root lookup after the earlier removal of `output/pdf/`.

**Acceptance:** Existing reachability tests and adapter tests pass; the new plan does not alter Stage 1–3 formal inputs or records.

**Outputs:** This plan, a baseline test record, and a root-lookup fix.

## P1 — Accounting case and ground truth

**Work:** Implement an inert allocation/spending ledger in flawed and repaired variants with identical public interfaces and initial state. Define the safety property as a pure calculation from recorded allocation and spending. Add deterministic Foundry tests for a known violating sequence on the flawed version, the same safe sequence on the repaired version, and ordinary legal operations in both. Explain the precise accounting error and correction.

**Acceptance:** All ground-truth assertions pass, including an independent calculation from concrete state; the property is not a dedicated goal flag and the defect is a real bookkeeping update error.

**Outputs:** Two fixture projects, Solidity regression tests, and a property/defect note.

## P2 — Separate execution consistency from safety

**Work:** Add a safety mode to scenario metadata, harness generation, concrete replay, Medusa observation, native seed conversion, statuses, and reports. Preserve the reachability mode. Validate actor, deployment, context, result, observer neutrality, and every declared state field separately from the business property. Keep the prefix concrete and solve only the final `uint256` argument.

**Acceptance:** Unit tests reject state, context, model, and replay mismatches; classify no candidate, timeout, tool error, and property-failure termination distinctly. A verified property violation records the call index and before/after states; safe executions remain visible.

**Outputs:** Safety-mode code, schema fields, reports, and focused tests.

## P3 — Real end-to-end acceptance

**Work:** Use a Medusa-executed prefix, Halmos model, fresh Foundry replay, and native Medusa replay to confirm one flawed-version violation. Replay the identical complete sequence against the repaired version. Keep the known regression sequence out of this search.

**Acceptance:** All four real tools' evidence links to one sequence and one computed property; prefix provenance, model, argument, before/after states, native execution, and repaired result are saved. Mock tests are labeled separately.

**Outputs:** A fresh acceptance run and a compact indexed evidence extract.

## P4 — Frozen 60-slot evaluation

**Work:** Freeze source hashes and the 32-second protocol after P3. Run ten paired warmup blocks per version and the three arms from the same block corpus. Charge common work, preparation, augmentation, solving, replay, and continuation under the existing budget ledger. Record warmup, augmentation, and continuation findings separately; censor misses at actual observation end. Preserve every negative result and failed attempt.

**Acceptance:** Exactly 60 completed slots with unmodified frozen semantics, complete raw records, 32-second budget evidence, and explicit randomness limitations. A semantic correction requires a fresh full affected matrix.

**Outputs:** Frozen config, raw study directory, slot observations, summary, and failure log.

## P5 — Independent audit and delivery

**Work:** Recompute counts, first-confirmed times, property truth, candidate confirmation, statuses, and checksums directly from raw Medusa events, native payloads, Halmos outputs, and Foundry replay evidence. Add a first-use demo and run it in a new output directory. Update README in English with Stage 4 commands, supported scope, measured results, and limits.

**Acceptance:** Independent audit passes all 60 slots; the demo works from a new path; unit, integration, Go, Solidity, and reachability compatibility checks pass. Published claims match audited evidence.

**Outputs:** `evidence/stage4/` index, results, acceptance record, checksums, audit, demo guide, and README update.

## Completion rule

Mark the Goal complete only when P1 ground truth, P3 real confirmation and repaired replay, P4 sixty slots with independent audit, required tests, and fresh demo all pass. The conclusion is limited to symbolic-assisted input generation and confirmed property violation in one known local teaching regression case; repaired-version misses are not a global safety proof.

## Acceptance status

P0–P5 are complete. The ground-truth Foundry tests, fresh real bridge, 60-slot frozen v2 matrix, raw-record audit, compatibility and integration tests, new-directory demo, and verified archive are recorded in [STAGE4_ACCEPTANCE.md](STAGE4_ACCEPTANCE.md). The v1 budget-overrun attempt and one v2 Medusa tool crash remain separate evaluation-invalid records. The v2 crash was recovered by rerunning its entire paired block with unchanged frozen inputs.
