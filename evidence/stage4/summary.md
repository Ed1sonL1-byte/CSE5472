# Stage 4 controlled safety regression

One known local accounting defect, one repaired version, and one arithmetic property.

Independent audit: **passed**, 60/60 slots.

| Version | Arm | Confirmed violations | Generated / confirmed candidates |
| --- | --- | ---: | ---: |
| accounting_flawed | native_resume | 10/10 | 0 / 0 |
| accounting_flawed | concrete_augment | 10/10 | 2304 / 0 |
| accounting_flawed | symbolic_augment | 10/10 | 9 / 9 |
| accounting_repaired | native_resume | 0/10 | 0 / 0 |
| accounting_repaired | concrete_augment | 0/10 | 2560 / 0 |
| accounting_repaired | symbolic_augment | 0/10 | 0 / 0 |

Misses are censored at each actual search observation end; 32 seconds is the budget ceiling.
Native controls are restarted from the paired warmup corpus. Medusa's internal corpus and mutation choosers retain clock-seeded randomness.
A repaired-version miss is finite testing evidence, not a proof of global safety.
