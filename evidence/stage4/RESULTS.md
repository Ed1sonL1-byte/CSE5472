# Stage 4 result boundaries

This fixed 60-slot comparison tests one known, local, inert accounting defect and its repair. Every slot passed the independent raw-record audit.

| Version | Arm | Confirmed slots | First finding stages (warmup / augmentation / import / continuation) | Generated / concrete-executed / confirmed candidates | Median first finding (s, hits only) |
| --- | --- | ---: | ---: | ---: | ---: |
| accounting_flawed | concrete_augment | 10/10 | 10 / 0 / 0 / 0 | 2304 / 2304 / 0 | 0.991 |
| accounting_flawed | native_resume | 10/10 | 10 / 0 / 0 / 0 | 0 / 0 / 0 | 0.991 |
| accounting_flawed | symbolic_augment | 10/10 | 10 / 0 / 0 / 0 | 9 / 9 / 9 | 0.991 |
| accounting_repaired | concrete_augment | 0/10 | 0 / 0 / 0 / 0 | 2560 / 2560 / 0 | — |
| accounting_repaired | native_resume | 0/10 | 0 / 0 / 0 / 0 | 0 / 0 / 0 | — |
| accounting_repaired | symbolic_augment | 0/10 | 0 / 0 / 0 / 0 | 0 / 0 / 0 | — |

Each arm in a version/repeat block starts from the same executed Medusa warmup corpus. First findings and misses use charged time; a miss is censored at the actual search observation end, while 32 seconds is only the budget ceiling.

| Version | Arm | No prefix | No candidate | Bounded timeout | Invalid model | Replay mismatch | Other statuses | Total augmentation / solver / replay seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| accounting_flawed | concrete_augment | 0 | 9 | 1 | 0 | 0 | — | 22.018 / 0.000 / 0.000 |
| accounting_flawed | native_resume | 0 | 0 | 0 | 0 | 0 | — | 0.000 / 0.000 / 0.000 |
| accounting_flawed | symbolic_augment | 0 | 0 | 1 | 0 | 0 | — | 23.397 / 16.735 / 1.865 |
| accounting_repaired | concrete_augment | 0 | 10 | 0 | 0 | 0 | — | 20.253 / 0.000 / 0.000 |
| accounting_repaired | native_resume | 0 | 0 | 0 | 0 | 0 | — | 0.000 / 0.000 / 0.000 |
| accounting_repaired | symbolic_augment | 0 | 0 | 10 | 0 | 0 | — | 20.319 / 19.599 / 0.000 |

Rejected candidates remain recorded in each audited observation. A bounded timeout is an augmentation outcome, never proof that the repaired contract is safe. Tool or evidence failures are evaluation-invalid and cannot be included in the 60 audited slots.

The v2 run encountered one Medusa coverage-metrics crash in a repaired symbolic slot. The failed paired block is preserved separately; its three arms were rerun under identical frozen inputs and only the completed block enters the 60-slot matrix. The earlier v1 budget-overrun attempt is also excluded.

The native control restarts Medusa from the paired warmup corpus. Medusa's internal corpus chooser and mutation strategy chooser remain clock-seeded, so paired arms do not have identical continuation trajectories. Any difference is descriptive for this one case; it is not a general performance claim.

The only supported conclusion is that symbolic-assisted input generation and concrete safety-violation confirmation work for one known local teaching regression, with a corresponding repaired comparison. This does not identify a new real-world vulnerability or prove the repaired version globally safe.
