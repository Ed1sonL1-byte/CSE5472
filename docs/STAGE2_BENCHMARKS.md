# Stage 2 Benchmark Protocol and Results

Stage 2 evaluates whether a concretely validated symbolic seed helps continued Medusa exploration after its full cost is charged. It covers four repository-owned teaching state machines. The results establish behavior for this fixed local protocol only; they do not identify vulnerabilities or establish performance on third-party contracts.

## Scenarios

| Fixture | Ready prefix | Goal call | Finite projection | Evaluation role |
| --- | --- | --- | --- | --- |
| `phase_counter` | 1–3 calls; observed phase 2 | `complete(uint256)` | phase 0–3, counter 0–19, unused 0, goal bool | Existing narrow exact condition |
| `bounded_ledger` | 1–3 calls; observed phase 2 | `settle(uint256)` | phase 0–3, total 0–30, reserved 0–23, goal bool | Existing narrow condition with separate accounting invariant |
| `range_gate` | exactly 2 calls; observed phase 2 | `passRange(uint256)` | phase 0–3, bound 0–30, offset 0–32, goal bool | Broad interval reachable by ordinary boundary values |
| `workflow_gate` | exactly 2 calls; observed phase 2 | `unlock(uint256)` | phase 0–5, lane 0–3, progress 0–4, goal bool | Segmented condition and two post-goal continuation states |

The scenario configuration declares allowed calls, readiness, prefix bounds, projection fields and bounds, and the goal observation. The campaign engine does not contain a fixture-specific target solution.

## Frozen comparison

The formal configuration is [`configs/stage2-benchmark.json`](../configs/stage2-benchmark.json). It fixes four fixtures, repeat ids 1–5, three rotated arm orders, 40 common warmup sequences, at most four prefixes and four accepted candidates, and one augmentation round.

| Arm | Work before native continuation |
| --- | --- |
| `native_resume` | None; restart from the common native corpus |
| `concrete_augment` | Up to 20 fixed boundary/seeded-random values per prefix, followed by fresh native validation |
| `symbolic_augment` | At most one bounded Halmos query per prefix, fresh Forge replay, build match, and native validation |

Each `(fixture, repeat)` performs one physical build and default-strategy Medusa warmup. Every arm receives a fresh copy of the same corpus and is charged the common work. The per-arm total budget is 8 seconds: common work, prefix handling, augmentation, solver, concrete replay, restart, startup replay, event recording, and continuation all draw from the same monotonic ledger. Augmentation has a 2.5 second cap; each Halmos query has a 0.75 second cap. Startup and continuation reserves prevent augmentation from consuming the whole campaign. CPU attribution is explicitly unavailable because portable full process-tree accounting was not available on the host; wall-clock is the primary budget.

Worker seed, fixture/repeat order, arm order, import filename order, and concrete random samples are controlled. Medusa v1.5.1's corpus chooser and mutation-strategy chooser use independent clock-seeded RNGs. The five repeats therefore sample separate executions; the arms do not claim identical random streams.

## Metrics

- **Sequence identity** hashes sender, receiver, value, calldata, and call order. It excludes nonce, block timing, filenames, and elapsed time.
- **State identity** hashes the declared finite projection. Raw arguments and whole-world state roots cannot manufacture a new projected state.
- **Coverage identity** is `(target runtime bytecode SHA-256, native marker)`. Getter and harness execution are excluded. Marker sets and positive hit counts are saved independently.
- **Import delta** compares startup replay with common warmup. **Continuation delta** compares new/mutated continuation sequences with the union of warmup and import. **Total delta** compares their union with warmup.
- **Seed attribution** filters real mutation events whose actual parent is an accepted seed, then computes state and coverage deltas from different executed children. It does not assign all continuation gains to the seed.
- **Goal hit** requires a concrete observation. The report distinguishes auxiliary validation, native startup import, native continuation, and right-censored misses. A miss is censored at its actual charged campaign observation end; 8 seconds is recorded separately as the budget limit. In this run the 22 censored observations ended between 6.394 and 7.286 seconds.

`benchmark-report` rebuilds `summary.json`, `summary.csv`, `summary.md`, and per-arm seed attribution only from saved JSON/events. It never invokes Medusa, Forge, Halmos, or a solver.

## Formal results

The selected run is `runs/stage2-formal-02`: 60/60 results are `evaluation_valid=true`. The first full attempt, `runs/stage2-formal-01`, retained 56 valid and four invalid deadline-boundary records; it is preserved and explicitly superseded after cleanup and deadline-result handling were fixed. The complete small extract is [`evidence/stage2`](../evidence/stage2/INDEX.md).

| Fixture | Arm | Goal hits | Total new states by repeat | Total new coverage by repeat | Accepted / used seeds |
| --- | --- | ---: | --- | --- | --- |
| bounded_ledger | native | 0/5 | 5, 10, 8, 15, 8 | 0, 0, 0, 17, 0 | 0 / 0 |
| bounded_ledger | concrete | 0/5 | 5, 10, 8, 14, 8 | 0, 0, 0, 17, 0 | 0 / 0 |
| bounded_ledger | symbolic | 5/5 | 6, 10, 9, 14, 8 | 1, 1, 1, 18, 1 | 5 / 5 |
| phase_counter | native | 0/5 | 5, 10, 7, 7, 6 | 0, 0, 0, 0, 0 | 0 / 0 |
| phase_counter | concrete | 0/5 | 5, 10, 7, 7, 6 | 0, 0, 0, 0, 0 | 0 / 0 |
| phase_counter | symbolic | 5/5 | 6, 11, 8, 8, 6 | 1, 1, 1, 1, 1 | 5 / 5 |
| range_gate | native | 5/5 | 22, 19, 17, 13, 18 | 8, 8, 0, 8, 8 | 0 / 0 |
| range_gate | concrete | 5/5 | 20, 19, 21, 17, 22 | 8, 8, 0, 8, 8 | 12 / 12 |
| range_gate | symbolic | 5/5 | 22, 15, 12, 18, 15 | 8, 8, 0, 8, 8 | 5 / 5 |
| workflow_gate | native | 5/5 | 2, 1, 1, 3, 2 | 11, 8, 23, 22, 7 | 0 / 0 |
| workflow_gate | concrete | 5/5 | 3, 8, 1, 6, 3 | 11, 24, 21, 22, 20 | 9 / 9 |
| workflow_gate | symbolic | 3/5 | 1, 0, 1, 3, 0 | 10, 7, 23, 22, 7 | 0 / 0 |

On the two narrow exact-condition fixtures, only symbolic augmentation reached the goal: 5/5 for each, with the accepted seed reaching the goal again during native startup replay. Every accepted symbolic seed was later selected as a mutation parent. Its children added 13 projected states for `phase_counter` and 11 for `bounded_ledger` across five repeats; child-attributed coverage was zero and one marker respectively.

`range_gate` reached the goal in all arms. Concrete accepted 12 seeds, symbolic accepted five, and every accepted seed was used, but all arms had the same per-repeat total coverage deltas. The extra solving work did not improve the hit rate on this easy condition.

`workflow_gate` records a negative symbolic result. Native and concrete reached the goal 5/5; symbolic reached 3/5 and accepted no seed. Its two misses have different causes: repeat 1 had no eligible prefix and spent zero time in symbolic augmentation, while repeat 2 made three symbolic attempts and spent 2.022 seconds in augmentation without accepting a seed. Symbolic's five-run median augmentation time was 1.994 seconds and median native continuation was 2.670 seconds versus 4.621 for native, but that cost cannot explain the no-prefix miss. The arms also traverse different trajectories because Medusa's corpus and mutation-strategy choosers use independent clock-seeded RNGs. Concrete accepted and used nine seeds; seed-attributed children added ten projected states and 48 coverage markers across repeats. These observations show an association between augmentation cost, available continuation, and outcomes in this fixture; they do not isolate a causal solver-cost effect or establish general superiority for concrete search.

Across all fixtures, 36 accepted seeds were distinct from their warmup sequences and all 36 were selected for at least one different executed mutation child. The mechanism-only diagnostic separately records one imported symbolic seed selected 110 times, with 85 different executed children.

## Reproduction and limits

```sh
./scripts/bootstrap.sh
./seedbridge doctor
./seedbridge benchmark --config configs/stage2-benchmark.json --output runs/stage2-new
./seedbridge benchmark-report runs/stage2-new
uv run --frozen python scripts/audit-stage2.py runs/stage2-new --output runs/stage2-new/audit.json
```

The committed evidence records exact config, source, fixture, adapter binary and lineage-patch hashes for the selected run. A new run can differ because of wall-clock scheduling and the documented internal RNG boundary. Five repeats are descriptive and too small for broad statistical claims. Coverage markers are meaningful only within the same fixture/runtime, and the four contracts were written for this project with known source and intentionally small state spaces.
