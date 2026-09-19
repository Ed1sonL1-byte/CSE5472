# Stage 1 local state-machine fixtures

These newly written, dependency-free fixtures exercise bounded reachability and
concrete regression checks. They are not production contracts, independently
sourced benchmarks, or vulnerability reproductions. Quantities are inert integers;
there are no funds, external calls, or address/time/gas-dependent decisions.

Both projects pin Solidity 0.8.36, the Shanghai EVM, and disabled optimization.
The concrete `test*` functions have no fuzz parameters. The separate `check_*`
functions provide Halmos smoke checks over symbolic `uint256` parameters.
The Foundry configuration limits test discovery to contracts ending in `Test`:
otherwise Foundry interprets the required `invariantHolds()` application interface
as one of its own invariant tests.

| Fixture | Successful prefix | Goal condition in phase 2 | `observe()` |
| --- | --- | --- | --- |
| `phase_counter` | `begin(); advance(delta)` | `arg0 == counter * 7 + 11` | `(phase, counter, 0, goal)` |
| `bounded_ledger` | `open(); reserve(units)` | `arg0 == total * 5 + reserved * 3 + 13` | `(phase, total, reserved, goal)` |

`advance` sets `counter = (delta % 17) + 3`. `reserve` sets
`reserved = (units % 23) + 1` and `total = reserved + 7`. Initial state is phase
0, the first prefix operation enters phase 1, and the second enters phase 2.
A matching final marker sets `goal = true` and phase 3. Calls in the wrong phase
or with the wrong final marker are no-ops, including inputs of `uint256.max`.
The terminal state is stable. `invariantHolds()` checks phase/goal consistency
and each fixture's bounded quantity relationships; it is independent of the
reachability marker equation.

## Local checks

Run commands from either project directory. To use an already installed compiler
without asking Foundry to download it, provide its absolute path:

```sh
forge test --offline --use /absolute/path/to/solc -vv
```

The compiler must report `0.8.36`. Halmos invokes `forge build` internally, so
the equivalent environment override is needed if that compiler is not already
in Foundry's version cache:

```sh
FOUNDRY_SOLC=/absolute/path/to/solc halmos \
  --contract PhaseCounterTest --function check_ \
  --solver-command '/absolute/path/to/z3' --solver-threads 1 \
  --solver-timeout-assertion 10s --no-status \
  --json-output halmos-smoke.json
```

Use `BoundedLedgerTest` in the second project. This checks local invariants and
out-of-order no-op behavior; passing these checks is not a proof about arbitrary
call histories or external contracts. See `VALIDATION.md` for actual results.
