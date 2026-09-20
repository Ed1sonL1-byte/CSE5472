# Stage 3 evidence index

This path-sanitized bundle summarizes the complete frozen Stage 3 study. The full 3.1 GB offline
archive remains at `artifacts/stage3-formal-v1.tar.gz`; its identity and offline verification are
recorded in `archive.json`.

| File | Evidence |
| --- | --- |
| `formal-config.json` | Frozen 320-slot matrix, seeds, budgets, query limits, and profile order |
| `formal-manifest.json` | Complete 40-block manifest, source/tool hashes, cache protocol, and no failed attempts |
| `audit.json` | Independent raw-event audit for all 320 slots |
| `summary.{json,md}` / `observations.csv` | Full descriptive results and every slot-level observation |
| `total-budget-goal-hits.svg` | Paired 8-second versus 32-second goal results |
| `goal-limit-hits.svg` | 0.50/0.75/1.50-second symbolic goal-invocation comparison |
| `charged-cost.svg` | Online charged-cost decomposition by profile |
| `protocol-audit.json` | Compact-format, timing, sequence-limit, codec, conversion, and storage smoke evidence |
| `baseline.json` | Stage 3 starting source, fixture, lockfile, patch, and Stage 2 evidence inventory |
| `superseded-run.json` | Preserved first formal attempt and the execution fix that required a full rerun |
| `archive.json` | Complete archive hash/size/file count and two independent offline rebuild hashes |
| `checksums.sha256` | SHA-256 for every other official file in this directory |

The study contains 320 valid slots in 40 shared-warmup blocks, 791,282 complete sequences, and
553,708 mutation events. It covers four repository-owned teaching state machines. Goal reachability
is not a vulnerability finding, and these descriptive results do not establish performance on
third-party contracts.
