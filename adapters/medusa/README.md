# Fixed-fixture Medusa adapter

This Stage 1 adapter uses `github.com/crytic/medusa v1.5.1` through its public Go APIs. It supports only the repository's `phase_counter` and `bounded_ledger` teaching fixtures. It does not accept another project path, RPC endpoint, arbitrary sender, deployment recipe, or target contract.

The adapter calls the real `Fuzzer.Start()` and saves actual executed native prefixes. It does not invent transaction sequences or manually fill fixture state. An exported native prefix is an adapter snapshot of Medusa's executed calls; Medusa separately retains coverage-increasing entries in `corpus/call_sequences/`.

## Build and environment

From the repository root, first install the Python lockfile and build both fixed fixtures using the project's documented environment. `loadFixture` requires their existing Forge artifacts. Then:

```sh
cd adapters/medusa
go build -o ../../.bin/medusa-adapter .
../../.bin/medusa-adapter version
```

The checked toolchain is Go 1.26.4 on Darwin arm64, Medusa v1.5.1, Forge 1.3.2, solc 0.8.36, and crytic-compile 0.3.11. A local module cache can be selected with `GOMODCACHE` and `GOCACHE`; no globally installed Medusa binary is needed. Put the repository `.venv/bin` first in `PATH`. In this workspace, compilation is explicitly pinned with:

```sh
export SOLC_VERSION=0.8.36
export FOUNDRY_SOLC="${SEEDBRIDGE_SOLC:-$HOME/.solc-select/artifacts/solc-0.8.36/solc-0.8.36}"
```

The Python bridge supplies these settings. The adapter never changes global solc-select state. Medusa invokes crytic-compile on the fixed Foundry project and the adapter compares its actual parsed ABI, init bytecode, and runtime bytecode with the Forge target. It also checks the runtime deployed by the worker. A mismatch aborts the run.

## Commands

All output paths must be new. Paths below are examples; run inside the repository so the fixed fixture locations can be resolved.

```sh
.bin/medusa-adapter run-observed \
  --fixture phase_counter --corpus-dir runs/example/corpus \
  --output runs/example/observed.json --seed 1 --tests 30 --max-steps 3

.bin/medusa-adapter roundtrip --fixture phase_counter \
  --input runs/example/observed.native/sequence-00002-prefix-2.json \
  --output runs/restart/corpus/call_sequences/input.json

.bin/medusa-adapter run-observed \
  --fixture phase_counter --corpus-dir runs/restart/corpus \
  --output runs/restart/observed.json --tests 1 --observe=true

.bin/medusa-adapter decode-corpus --fixture phase_counter \
  --input runs/restart/corpus/call_sequences/input.json \
  --output runs/restart/decoded.json

.bin/medusa-adapter encode-candidate --fixture phase_counter \
  --input runs/restart/corpus/call_sequences/input.json \
  --argument 123 --output runs/candidate/call_sequences/input.json
```

`--argument` is a candidate supplied by the bridge, not a claim that the example value reaches a goal. `encode-candidate` appends `complete(uint256)` or `settle(uint256)` using native `CallMessageDataAbiValues` and `CallSequence` serialization. It inherits the fixed actor/target from the last call and increments its nonce. A prefix must contain 1–3 calls. The exported candidate may contain 2–4 calls. `roundtrip` and `decode-corpus` also accept `--prefix-length N`.

`--tests` counts **complete sequences**, rather than transactions. It is implemented by stopping at `CallSequenceTested`, after Medusa has processed native admission. Fresh warmup defaults to 3 calls per sequence and permits `--max-steps 1..4`. Restart requires `--tests` to equal the number of input JSON files initially present in `call_sequences/`; no new fuzzed sequence is generated after those inputs. Use a fresh directory containing one seed for an unambiguous single-seed acceptance check. `test_results` imports are rejected.

The timeout is a secondary wall-clock guard starting after compilation. A timeout writes partial evidence and returns an error. The caller must separately bound the whole subprocess, including compiler execution.

## Output schema 1

The report records versions, fixture, RNG strategy, seed, configuration path, actual build hashes, deployment, completion status, and `sequences`. Every `sequences` entry corresponds to one executed prefix, so `native_path` contains exactly as many calls as `steps`. The last prefix in a completed sequence has `is_complete_sequence=true`.

- `native_digest`: SHA256 of the exact native file bytes, including its terminal newline.
- `medusa_hash`: Medusa's native call-sequence identity; it is distinct from the file digest.
- `origin`: `native_generated_prefix` or `native_imported_prefix`.
- `steps`: actual `from`, `to`, `nonce`, `value`, `calldata`, ABI `signature`/`arguments`, `status`, `success`, `block_number`, `block_timestamp`, receipt gas and return data.
- `observe`: three decimal strings and a JSON boolean. `goal` repeats the final boolean. `invariant_holds` is a separate observation.
- `state_digest_sha256`: SHA256 of the ABI-encoded `observe()` return data. It covers only the fixture's declared projection, not complete cross-engine world-state equality.
- `state_root_before_observer` / `state_root_after_observer`: Medusa state roots around view readbacks. The adapter rejects a persistent change.
- `coverage_digest_sha256`: SHA256 of ordered big-endian `(native marker uint64, hit count uint64)` pairs for the target runtime. Cumulative digest/count fields and a final top-level digest are also present.

Coverage is copied via a transaction-only public tracer callback before native corpus processing frees the per-transaction map. The adapter queries Medusa's public `GetContractCoverageMap`/`HitCount` APIs. It enumerates possible markers from the fixed runtime and requires the number found to equal `BranchesHit()`, failing closed if a native marker cannot be represented. Getter calls do not run through the transaction coverage tracer. No private fields, reflection into the chooser, or Medusa source patches are used.

`--observe=false` omits getter calls and yields null projection/goal/invariant values, while retaining transaction receipts, state-root readouts, and coverage instrumentation. The integration comparison tests the effect of adding getter observation; it does not claim that all adapter instrumentation is absent in the off run.

## Restart and admission evidence

`replayed_by_medusa` is true only for a complete startup sequence whose native hash and length match an input file. `admitted_for_mutation` additionally requires the native `CallSequenceTested` event, no timeout cancellation, and no shrink requests. The adapter disables all test providers and its observation hook returns no shrink requests.

At pinned v1.5.1, `testNextCallSequence` calls `MarkCallSequenceForMutation` after a successful complete startup replay; that method adds to the native chooser and returns nil. The worker emits `CallSequenceTested` after this path returns. Evidence is consequently labeled `medusa_v1.5.1_post_sequence_event` with its source link and conditions. This is source-bound control-flow evidence; it is not a direct inspection of private chooser contents or proof that the seed was later chosen for mutation. No final-call hook stops the worker early.

## Determinism and scope

Stage 1 uses one worker, fixed sender `0x10000`, deployer `0x30000`, value zero, zero requested delays, checked nonces, and fixed gas/fees. Requested zero delay still permits Medusa to create a new block; output records actual execution context.

The public generator hook seeds the worker RNG, sorts the target's exposed method list, selects Medusa's native `RandomValueGenerator`, and sets `NewSequenceProbability=1`. It does not implement a custom transaction generator. Medusa's independent clock-seeded corpus choosers are not invoked in this mode. This is a reproducible integration configuration, **not stock Medusa and not a performance baseline**. The native restart path remains intact. Reproducibility excludes elapsed times, generated filenames, and absolute directory names; exact native call files and step observations are the comparison artifacts.

## Verification

```sh
cd adapters/medusa
go test -v ./...
SEEDBRIDGE_INTEGRATION=1 go test -v -run TestNativeRestartObserverAndDeterminism ./...
```

The integration command requires the pinned compiler environment above. On 2026-09-18 it passed for both fixtures: 30 native sequences repeated exactly per fixture; a real two-call prefix round-tripped and restarted with readbacks on/off; state roots, receipts, contexts, native coverage digests, and admission evidence agreed. Unit tests verify maximum uint256 precision, native codec stability, candidate bounds, and rejection of incompatible calldata/ABI metadata and unsupported execution context.

`test-runs/` contains local debugging evidence and is not required for the adapter. The early `phase-warmup`/`restart-on` folders predate corrected account-check and coverage settings; use `phase-v2` and `restart-v2-on` for current examples.
