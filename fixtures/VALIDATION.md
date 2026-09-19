# Fixture validation evidence

Executed locally through 2026-09-19 America/New_York, on Darwin arm64.
Tools: Forge 1.3.2-stable, Solidity 0.8.36+commit.8a079791, Halmos 0.3.3.
Compiler settings: Shanghai EVM, optimizer disabled, no external libraries.

## Concrete checks

Run from each project directory:

```sh
forge test --offline --use /Library/Frameworks/Python.framework/Versions/3.13/bin/solc -vv
```

| Project | Passed | Failed | Process exit code |
| --- | ---: | ---: | ---: |
| `phase_counter` | 4 | 0 | 0 |
| `bounded_ledger` | 4 | 0 | 0 |
| `range_gate` | 4 | 0 | 0 |
| `workflow_gate` | 4 | 0 | 0 |

The original concrete tests cover out-of-order no-ops, an incorrect marker followed by
the exact marker, `uint256.max` inputs, accounting/phase invariants, and terminal
state stability. `range_gate` also checks ordinary value 32 against its broadest
range. `workflow_gate` checks both post-goal `continueWork` branches and their
finite states. The initial run exposed Foundry's discovery of the application
method `invariantHolds()` as a standalone invariant test. Both projects now set
`match_contract = ".*Test$"`; the recorded successful run used that setting.

## Symbolic invariant smoke

From `phase_counter`:

```sh
FOUNDRY_SOLC="${SEEDBRIDGE_SOLC:-$HOME/.solc-select/artifacts/solc-0.8.36/solc-0.8.36}" \
FOUNDRY_OFFLINE=true uv run --frozen halmos \
  --contract PhaseCounterTest --function check_ \
  --solver-command "$(git rev-parse --show-toplevel)/.venv/bin/z3" \
  --solver-threads 1 --solver-timeout-assertion 10s --no-status \
  --json-output halmos-smoke.json
```

From `bounded_ledger`, use the identical command with `BoundedLedgerTest`.

| Project | Test | Result | Paths | Bounded loops | Counterexample models |
| --- | --- | --- | ---: | ---: | ---: |
| `phase_counter` | `check_initialNoops(uint256,uint256)` | PASS | 1 | 0 | 0 |
| `phase_counter` | `check_invariant(uint256,uint256)` | PASS | 5 | 0 | 0 |
| `bounded_ledger` | `check_initialNoops(uint256,uint256)` | PASS | 1 | 0 | 0 |
| `bounded_ledger` | `check_invariant(uint256,uint256)` | PASS | 7 | 0 | 0 |

Both listed Stage 1 Halmos processes exited 0. Raw structured results are retained as
`phase_counter/halmos-smoke.json` and `bounded_ledger/halmos-smoke.json`.
The symbolic tests check the explicit operation sequences in their source;
they do not prove invariants over every possible transaction history.

Forge emitted a nonfatal warning because its optional user-wide signature cache
was outside the writable sandbox. Halmos's build also emitted naming-style notes
for the intentional `check_` prefix. Neither changed the recorded test outcomes.

Both added fixtures also completed the same Stage 1 codec → harness → Halmos →
fresh Forge replay → Medusa reseed flow with `stage1_confirmed`; the compact
result is tracked in `evidence/stage2/new-fixture-stage1-validation.json`.
These results do not constitute security-vulnerability detection.
