# Stage 4 acceptance record

Owner: Edison Li

## Decision and scope

All Stage 4 completion gates passed for one known, local, inert integer-accounting regression case. This record does not claim a new real-world vulnerability or global safety of the repaired version. The earlier reachability results remain reachability results.

## Ground truth and real bridge

The business property is `allocated == spent + remaining`, calculated independently from three concrete counters after each call. Both Solidity variants share the same interface and zero state. Foundry regression tests confirm that `open(); spend(100)` violates the property only in the flawed version; partial legal spends and rejected operations behave as specified in both versions. The known sequence is used only for these regression tests, not as a formal warmup seed or candidate-generator input.

The fresh run under `runs/stage4-demo-fresh-01/` returned `safety_confirmed`. A one-call Medusa-executed `open()` prefix (case `3f90a11dbe691b8418a3c119630b858038c499aacf7a3cf819f3043f271a263f`) was checked concretely. Halmos solved the final `spend(uint256)` argument as `100`; a new Foundry deployment confirmed the first violation at call index 1, and native Medusa replay executed the same complete sequence. The independently computed state changed from `(allocated=100, spent=0, remaining=100)` to `(100, 0, 0)` in the flawed contract. On a new deployment of the repaired contract, the same sequence ended at `(100, 100, 0)` with the property holding. Observer neutrality and native roundtrip checks passed. The prefix file, model, full native sequence, before/after states, and raw replay references are indexed in `evidence/stage4/acceptance.json`.

## Formal comparison and independent audit

The frozen `configs/stage4-safety-v2.json` protocol has 2 variants × 3 strategies × 10 repeats under one 32-second total budget. Each version/repeat block shares one executed Medusa warmup corpus across its three strategies. The independent audit recomputed property truth, counts, candidate confirmations, first findings, and censoring from raw Medusa events, Halmos model files, and Foundry/Medusa concrete execution records. It passed **60/60 evaluation-valid slots** and 20/20 paired blocks, covering 179,244 complete sequences and 125,573 mutation events.

| Variant | Native resume | Concrete augment | Symbolic augment |
| --- | ---: | ---: | ---: |
| Flawed: confirmed-violation slots | 10/10 | 10/10 | 10/10 |
| Repaired: confirmed-violation slots | 0/10 | 0/10 | 0/10 |
| Flawed: generated / executed / confirmed augmentation candidates | 0 / 0 / 0 | 2,304 / 2,304 / 0 | 9 / 9 / 9 |
| Repaired: generated / executed / confirmed augmentation candidates | 0 / 0 / 0 | 2,560 / 2,560 / 0 | 0 / 0 / 0 |

All 30 flawed-version first findings occurred in the common warmup, so this matrix does not show a first-finding advantage for augmentation. The nine symbolic candidates are later, independently executed confirmations. The 30 repaired-version misses are right-censored at their actual search observation ends (23.343–24.721 seconds), not at the 32-second budget ceiling. The concrete generator's 4,864 executed candidates that did not violate the property remain recorded as `goal_false`; the repaired symbolic arm had ten bounded augmentation timeouts. No repaired candidate was accepted as a violation.

The first formal attempt, v1, stopped after 45 valid slots because a native evidence-decoding stage exceeded its charged budget. Its raw record is preserved and excluded. The frozen v2 protocol reserves nine seconds within the same budget for native setup/evidence work and reran all 60 slots. During v2, Medusa v1.5.1 crashed once in a coverage-metrics goroutine during a repaired symbolic slot. That tool error and the entire first paired block are preserved under `runs/stage4-formal-v2/failed-block-attempts/` and in the raw archive; the complete block was rerun with unchanged frozen inputs. No failed attempt is counted as an evaluation-valid negative result.

## Verification and reproducibility

- `./scripts/bootstrap.sh` and `./seedbridge doctor`: passed; the rebuilt Medusa adapter hash matches the formal manifest.
- Foundry ground truth: 3/3 tests passed for each accounting contract.
- `SEEDBRIDGE_INTEGRATION=1 uv run --frozen pytest -q`: 169/169 passed, including real toolchain acceptance and reachability compatibility tests.
- `CGO_ENABLED=0 GOTOOLCHAIN=local go test -mod=readonly ./...` in `adapters/medusa/`: passed.
- `./seedbridge safety-audit runs/stage4-formal-v2`: passed 60/60 from raw records.
- The new-directory demo in `runs/stage4-demo-fresh-01/` returned `safety_confirmed`.
- `scripts/archive-stage4.py --verify` checked all 31,850 archived files and passed; the archive SHA-256 is `f908c1d03f4b60f85a4525a7c7c4a6f354d1b39edd41fdd299142bdb13727377`.
- `shasum -a 256 -c evidence/stage4/checksums.sha256`: passed for every public extract.

The public index is `evidence/stage4/INDEX.md`, the interpretation is `evidence/stage4/RESULTS.md`, and the complete 647,530,218-byte local raw archive is `artifacts/stage4-formal-v2.tar.gz` (ignored by Git). `STAGE4_DEMO.md` gives the first-use commands. The native control restarts from the paired warmup corpus; Medusa's internal continuation choices retain clock-seeded randomness. These limits, the warmup ceiling effect, and finite repaired-version observation bound the conclusion.
