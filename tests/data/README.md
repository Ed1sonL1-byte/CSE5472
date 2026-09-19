# Native Halmos output samples

`halmos033-prefix.json` and `halmos033-goal.json` are unmodified JSON outputs
captured from the project's Halmos 0.3.3 and Z3 4.12.6 environment on
2026-09-18 America/New_York. They were produced by `run_halmos()` against a
`generate_harness()` project for the repository-owned `PhaseCounter` fixture.

The concrete prefix was `begin(); advance(5)` at block 12 / timestamp 100,
with a zero-value sender consisting of twenty `0x11` bytes and a recorded target
consisting of twenty `0x22` bytes. Observations were `(1,0,0,false)` and
`(2,8,0,false)`. The recorded deployment actor consists of twenty `0x33` bytes.
The generated project maps the recorded target to a new fixture instance.

The separate prefix check passed. The reachability check emitted the typed
`arg0 = 67` model. A second generated project concretely ran `test_replay()`
with this argument under Forge 1.3.2 and passed its false-to-true goal assertion
and independent fixture invariant. Compilation used Solidity 0.8.36, Shanghai,
and disabled optimization.

These samples establish parser compatibility and local fixture replay only.
They are not native Medusa corpus evidence or security-vulnerability findings.
