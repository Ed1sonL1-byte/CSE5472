# Local state-machine fixtures

These four dependency-free fixtures exercise bounded reachability, replay, and continued exploration. They are repository-owned teaching contracts, not production contracts, third-party benchmarks, or vulnerability reproductions. They hold inert integers and make no external calls.

Every project pins Solidity 0.8.36, the Shanghai EVM, and disabled optimization. Concrete `test*` functions have no fuzz parameters. Separate `check_*` functions expose one symbolic `uint256` to Halmos. Foundry discovers only contracts ending in `Test`, so the application method `invariantHolds()` is not mistaken for a Foundry invariant test.

| Fixture | Ready prefix | Symbolic suffix | State projection | Role |
| --- | --- | --- | --- | --- |
| `phase_counter` | `begin(); advance(delta)` | `complete(arg0)` | `(phase, counter, 0, goal)` | Narrow exact condition |
| `bounded_ledger` | `open(); reserve(units)` | `settle(arg0)` | `(phase, total, reserved, goal)` | Narrow exact condition with independent accounting invariant |
| `range_gate` | `begin(); configure(mode)` | `passRange(arg0)` | `(phase, bound, offset, goal)` | Broad interval reachable by ordinary boundary values |
| `workflow_gate` | `start(); choose(lane)` | `unlock(arg0)` | `(phase, lane, progress, goal)` | Segmented predicate; `continueWork` reaches two post-goal states |

Calls in an invalid phase are no-ops. Each fixture declares finite bounds for the three numeric observation fields and exposes a separate boolean goal. `invariantHolds()` checks state consistency independently of the reachability predicate. The same Python and Go engine code handles all four fixtures; scenario-specific operation names, prefix bounds, readiness, state fields, and finite domains live in `src/seedbridge/config.py` and `adapters/medusa/fixture.go`.

Run concrete checks from any project directory:

```sh
forge test --offline --use /absolute/path/to/solc-0.8.36 -vv
```

Run a symbolic smoke check with the fixture's test contract:

```sh
FOUNDRY_SOLC=/absolute/path/to/solc-0.8.36 halmos \
  --contract PhaseCounterTest --function check_ \
  --solver-command /absolute/path/to/z3 --solver-threads 1 \
  --solver-timeout-assertion 10s --no-status \
  --json-output halmos-smoke.json
```

Passing a fixture test establishes only the behavior encoded in that local contract. Cross-engine replay, native corpus handling, lineage, and benchmark evidence are validated separately in `docs/STAGE1_VALIDATION.md` and `docs/STAGE2_VALIDATION.md`.
