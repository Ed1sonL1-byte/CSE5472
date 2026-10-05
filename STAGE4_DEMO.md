# SeedBridge Stage 4 first-use demonstration

This guide reproduces one local, known accounting-property violation with real Medusa, Halmos, and Foundry executions. It uses a fresh output directory. It does not reproduce the 60-slot formal comparison unless you run the later study command.

## 1. Prepare and check the pinned tools

From the repository root:

```sh
./scripts/bootstrap.sh
./seedbridge doctor
```

Bootstrap installs the locked Python environment, prepares the fixed Medusa v1.5.1 adapter, and builds all supported local fixtures. It does not install Go or Forge. `doctor` must report every tool as `OK` before an acceptance run.

## 2. Establish case ground truth

```sh
FOUNDRY_SOLC="$HOME/.solc-select/artifacts/solc-0.8.36/solc-0.8.36" \
  FOUNDRY_OFFLINE=true forge test --root fixtures/accounting_flawed
FOUNDRY_SOLC="$HOME/.solc-select/artifacts/solc-0.8.36/solc-0.8.36" \
  FOUNDRY_OFFLINE=true forge test --root fixtures/accounting_repaired
```

The flawed version's full spend leaves `allocated=100`, `spent=0`, and `remaining=0`; the repaired version records `allocated=100`, `spent=100`, and `remaining=0`. Both versions pass partial-spend and rejected-operation tests. The known test input is not supplied to the demonstration's Medusa corpus or Halmos query.

## 3. Run the real bridge in a new directory

Choose a path that does not exist. For example:

```sh
./seedbridge safety-demo \
  --seed 1 --warmup-tests 100 --max-prefixes 5 \
  --output runs/stage4-demo-fresh
```

The command exits successfully only when it reports `safety_confirmed`. Its `report.json` links to the raw prefix file, Halmos model, fresh Foundry replay, native Medusa candidate and observation, and the same-sequence repaired replays. The report records the first violating call index and the independently calculated before/after accounting states. The native observer's property read must agree with the arithmetic calculation.

Inspect the result:

```sh
./seedbridge report runs/stage4-demo-fresh
```

The generated directory is ignored by Git; preserve it as raw acceptance evidence. A safety demo can legitimately return `no_eligible_prefix`, `no_witness_within_bounds`, `timeout`, or a classified error for some random seeds. A failed run is not a property proof. The published acceptance record identifies a specific successful real run.

## 4. Rebuild the formal result from raw records

The frozen comparison uses two versions, three arms, ten repeats, and one 32-second total budget:

```sh
./seedbridge study-plan --config configs/stage4-safety-v2.json
./seedbridge safety-study --config configs/stage4-safety-v2.json \
  --output runs/stage4-review
./seedbridge safety-audit runs/stage4-review
./seedbridge safety-report runs/stage4-review
```

The audit reads raw Medusa event payloads, selected native prefix files, candidate execution records, Halmos models, and Foundry replay results. It recomputes property truth and critical counts rather than comparing summary files alone. `evidence/stage4/` contains the published index, sanitized observations, results, and checksums. The formal run records the actual search observation end for misses; 32 seconds is a budget ceiling.

The native control restarts Medusa from the common warmup corpus. Medusa's internal corpus and mutation choosers retain clock-seeded randomness, so paired warmups do not guarantee identical continuation trajectories. This demonstration and comparison concern one known, inert teaching defect. They do not establish a new real-world vulnerability or a global safety proof for the repaired contract.
