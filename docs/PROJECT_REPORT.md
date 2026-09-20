# SeedBridge: Concrete Prefixes, Symbolic Last-Step Seeds, and Reproducible Hybrid Evaluation

## Abstract

SeedBridge is a local research prototype that connects Medusa, Halmos, and Foundry for a deliberately
narrow hybrid-testing workflow. Medusa first executes concrete transaction sequences. SeedBridge then
selects a one-to-three-call prefix whose target is still false, asks Halmos to solve one `uint256`
argument for the final call, validates the candidate by replaying it against a fresh deployment, and
imports the exact native sequence into a restarted Medusa campaign. The project records whether the
seed was executed, admitted to mutation, and selected as a real mutation parent.

The Stage 3 study evaluates budget sensitivity and reproducibility on four repository-owned teaching
contracts. A frozen matrix contains 320 distinct slots in 40 shared-warmup blocks. All slots passed an
independent raw-event audit. Across the four fixtures, the 8-second profiles reached the goal in 17/40
native, 22/40 concrete-augmentation, and 39/40 symbolic-augmentation runs. The corresponding 32-second
profiles reached 20/40, 25/40, and 40/40. At 32 seconds, changing the symbolic goal-invocation process
limit among 0.50, 0.75, and 1.50 seconds did not change the 40/40 goal count. These results demonstrate
the mechanism and expose its cost boundaries on the chosen fixtures; they do not establish a security
finding or general performance advantage on third-party contracts.

## 1. Problem and scope

Stateful smart-contract fuzzers are effective at executing many concrete call sequences, but narrow
integer predicates can remain difficult to reach. Symbolic execution can solve such predicates, but
running it over an unrestricted transaction history is expensive and complicates faithful replay.
SeedBridge studies a small interface between the two approaches: preserve a concrete history already
executed by the fuzzer, symbolize only the next call's single integer argument, validate the result
concretely, and return the resulting native sequence to the fuzzer.

The implementation intentionally fixes the caller, uses zero transaction value, permits one symbolic
`uint256`, limits concrete prefixes to one through three calls, limits complete sequences to four
calls, uses one Medusa worker, and performs one augmentation batch. The supported targets are four
local contracts: `PhaseCounter`, `BoundedLedger`, `RangeGate`, and `WorkflowGate`. The first two use
narrow target conditions, the third has a broad target range, and the fourth makes continuation time
and workflow order visible. The project does not accept arbitrary contracts, multiple actors, complex
ABI values, or multi-step symbolic suffixes.

The work builds on Medusa's stateful fuzzing and corpus mutation, Halmos's symbolic test execution, and
Foundry's concrete EVM testing. Related hybrid systems such as Optik motivate combining symbolic input
generation with fuzzing. SeedBridge's contribution is the constrained integration, evidence chain,
and evaluation protocol rather than a claim that hybrid fuzzing itself is new.

## 2. System design

The workflow begins with a pinned Medusa v1.5.1 adapter. Its small lineage patch exposes the generation
identifier and actual parent selected by Medusa's existing strategy; it does not add random choices or
change selection weights. The adapter records every complete execution once in a gzip JSONL stream.
Each record contains the exact native payload, call identity and context, outcome, finite-state
projection, runtime coverage markers, all executed prefix identities, generation kind, parent hashes,
and relative execution time. An EOF record provides counts and a stream checksum.

SeedBridge chooses only prefixes that Medusa actually executed and for which the fixture's goal is
false. Halmos first checks that the concrete prefix replays under the fixed actor and context. A
generated target test then makes the final argument symbolic. Parsed models must match the expected
test identity and type. A separate Foundry project deploys a fresh contract, replays the concrete
prefix plus model value, and confirms the target transition. This independent concrete replay prevents
a solver output alone from being treated as a successful seed.

The fixed native codec exports the accepted sequence in the format used by Medusa's corpus. Restarted
Medusa execution establishes three different facts: the sequence was imported, it was actually
executed, and it became eligible for mutation. Lineage records can then show whether it was selected as
a parent and whether the executed child differs. The engine contains fixture metadata and observation
rules but no hard-coded target solution.

Errors remain separate from valid negative outcomes. Tool failures, malformed or incomplete event
streams, invalid models, replay mismatches, state mismatches, and sequence-limit stops make an
evaluation invalid. A complete run may validly end with no eligible prefix, no candidate, a bounded
augmentation timeout, or no observed goal. Tool errors take precedence when a timeout and a process
failure occur together.

## 3. Evaluation protocol

Stage 3 asks three questions. RQ1 measures what changes when the total budget increases from 8 to 32
seconds while the augmentation policy remains fixed. RQ2 fixes the total budget at 32 seconds and
changes only the Halmos goal-invocation process limit among 0.50, 0.75, and 1.50 seconds. RQ3 identifies
where online time is charged and distinguishes the reasons for negative outcomes.

The primary matrix contains four fixtures, three arms, two budgets, and ten repeats, for 240 slots. The
goal-limit comparison contains three symbolic profiles at 32 seconds. Its 0.75-second profile reuses the
same 40 primary slots, so only 80 new slots are added. The complete study therefore has 320 distinct
slots rather than 360.

Each fixture/repeat block performs one 40-sequence warmup. Its eight profiles receive identical
prefix-pool, corpus, source, and compiled-cache snapshots. Each profile works on a private copy so that
new cache or corpus state cannot leak to another profile. Common work is physically performed once but
charged once to each logical profile. Profile order rotates by repeat and execution is sequential.

The online ledger separates common build and warmup, input and cache preparation, prefix-pool work,
augmentation, seed import, native startup and continuation, and evidence validation. The Go adapter
separately reports search start, search stop, last complete observation, event-stream completion, and
evidence-flush completion. Goal times and right-censoring use actual complete observations. Flush and
offline report generation cannot extend the search interval. Requested and effective prefix/goal
process limits are both saved. The goal-invocation value is a subprocess wall-clock limit that includes
startup and related checks; it is not presented as isolated SMT CPU time.

The formal run used a frozen configuration and source snapshot. The first formal attempt was preserved
after an invalid block exposed an orphan native candidate written just before a symbolic timeout. The
adapter correctly rejected the disagreement between accepted entries and imported corpus files. The
fix deletes only fresh codec outputs that were not committed as accepted entries, and a targeted
regression test covers the case. Because this changed execution code, the project did not resume or
mix results. It froze a new snapshot and reran all 320 slots.

## 4. Results

The completed run contains 791,282 complete sequences and 553,708 mutation events. The independent
auditor parsed the raw streams without calling the production segmented-metrics function. It checked
the exact matrix, fixed actor and value, finite-state ranges, coverage markers, native payload digests,
prefix dictionaries, parent-before-child ordering, accepted-seed replay and use, timing boundaries,
common cache/corpus identities, and goal observations. All 320 slots passed; all 40 blocks completed,
and the selected run has no failed block attempts.

### 4.1 Total-budget sensitivity

At 8 seconds, native reached 17/40 goals, concrete augmentation 22/40, and symbolic augmentation 39/40.
At 32 seconds, the counts were 20/40, 25/40, and 40/40. In paired fixture/repeat comparisons, the
longer budget added three native hits, three concrete hits, and one symbolic hit, with no hit-to-miss
reversals.

The aggregate hides an important fixture boundary. On `PhaseCounter` and `BoundedLedger`, native was
0/20 at both budgets, concrete augmentation was 5/20 at both budgets, and symbolic augmentation was
20/20 at both budgets. Extra continuation time did not solve those narrow conditions. On `RangeGate`,
all native and symbolic profiles hit; concrete improved from 9/10 to 10/10. On `WorkflowGate`, native,
concrete, and symbolic improved from 7/10, 8/10, and 9/10 to 10/10 each. The longer budget therefore
helped the broad/workflow fixtures rather than the narrow integer gates.

The 32-second profiles executed many more sequences. Relative to paired 8-second profiles, the mean
increase was about 2,937 sequences for native, 2,706 for concrete augmentation, and 2,496 for symbolic
augmentation. Finite-state counts also increased, but Medusa's disclosed clock-seeded corpus and
mutation-strategy choosers produce different continuation trajectories. Those state differences are
descriptive and cannot isolate an arm's causal contribution.

### 4.2 Goal-invocation limit

All three 32-second symbolic profiles reached 40/40 goals. Compared with 0.75 seconds, the 0.50-second
limit had no goal or accepted-seed difference. The 1.50-second limit accepted one additional seed but
also had no goal-count or runtime-coverage difference. The paired aggregate finite-state deltas were
+19 for 0.50 seconds and +6 for 1.50 seconds relative to 0.75 seconds, but individual deltas varied in
both directions and remain mixed with independent Medusa continuation randomness.

The defensible result is that the chosen fixtures did not benefit in goal reachability from increasing
the per-invocation limit beyond 0.50 seconds under the fixed 2.5-second augmentation cap. It would be
incorrect to infer a universal optimal solver timeout from three process limits and four constructed
targets.

### 4.3 Cost and negative outcomes

The mean shared build/warmup charge was 0.987 seconds per logical profile. For 8-second runs, native
used an average of 5.250 seconds for startup and continuation. Concrete augmentation used 0.854 seconds
and left 4.389 seconds for native work. Symbolic augmentation used 1.821 seconds and left 3.402 seconds.
At the longer budget, concrete augmentation averaged 0.877 seconds and symbolic augmentation
1.825–1.833 seconds; most additional time went to continuation. Cache copying, seed import, and online
evidence checks were small but recorded rather than omitted.

Across all slots, 151 goals were first observed after native import, 52 during native continuation, and
40 during the common warmup. There were 43 valid continuation misses, 31 no-candidate outcomes, two
no-eligible-prefix outcomes, and one bounded augmentation timeout. These categories prevent a negative
row from being assigned automatically to symbolic-solving overhead. For example, the short-budget
`WorkflowGate` rows include no-prefix, no-candidate, augmentation-timeout, and native-continuation
misses, as well as independent search trajectories.

## 5. Reproducibility and evidence

The compact format reduced a conversion of the 60 Stage 2 campaigns from 5,589,753,302 bytes of legacy
campaign JSON to 129,776,533 bytes of event streams while reproducing all 29,259 complete-sequence,
20,382 mutation, state, coverage, and lineage counts. Corruption tests cover missing EOF, truncation,
duplicate identifiers, invalid native payloads, bad prefix dictionaries, absent parents, and checksum
failure. Controlled tests show that a delayed flush changes stream/charged completion without changing
search stop or the last observation.

The Stage 3 formal archive is `artifacts/stage3-formal-v1.tar.gz`. It is 3,358,084,381 bytes with
SHA-256 `91bf6e5063a4d7644e0f84a1c8187480a35c66185e4f929d275384db6ad2ad25`.
It contains 43,482 study files, exact raw streams, native seeds, model/replay evidence, the frozen source
snapshot, derived reports, and a per-file manifest. A new directory verified every member and ran the
standard-library-only rebuild twice without Medusa, Halmos, Foundry, solc, Z3, Go, or network access.
Both rebuilds produced the same Markdown, CSV, and logical summary. A path-sanitized public evidence
index, all 320 observations, audit, tables, and charts are stored under `evidence/stage3/`.

## 6. Threats to validity and limitations

The four contracts are small, known-source teaching fixtures. Their goals are intentional and their
finite-state projections omit the full EVM world state. Goal reachability is not a vulnerability. The
study does not test third-party protocols, external calls, multiple actors, payable paths, complex ABI
types, long transaction histories, or adversarial environment dependencies.

The native control is Medusa's default generator and mutator restarted from a shared warmup corpus. It
is not an uninterrupted stock-Medusa run. Restart and import costs are charged consistently, but this
control answers a narrower question. The ten repeats share warmup within each block, and some Medusa
chooser randomness is clock seeded. The 320 slots are paired observations, not 320 independent samples.
The study reports descriptive counts and paired deltas rather than significance claims.

Only two total-budget levels were tested, so the result is a two-point comparison rather than a
performance curve. The three Halmos limits bound an entire subprocess and do not isolate solver CPU
time. Finally, concrete augmentation uses a frozen boundary dictionary appropriate to the teaching
fixtures; its performance should not be treated as a general concrete-search baseline.

## 7. Conclusion

SeedBridge demonstrates an evidence-preserving path from real Medusa executions to a one-argument
Halmos query, independent concrete confirmation, native seed import, and observed mutation lineage.
On the two narrow fixtures, symbolic augmentation consistently supplied goal-reaching seeds where
additional native continuation did not. On the broad and workflow fixtures, more continuation time
closed most short-budget gaps, and symbolic work consumed time that could otherwise support native
search. Changing the symbolic invocation limit did not change goal counts in this matrix.

The central result is therefore conditional: symbolic last-step augmentation is useful for the chosen
narrow predicates, while its budget value depends on target structure and the opportunity cost of
continuation. The complete raw evidence, explicit negative categories, preserved failed attempt, and
offline rebuild make that limited conclusion inspectable without overstating it.
