# Stage 3 Study Results

Independent audit: **passed**. The study contains 320 distinct slots in 40 shared-warmup blocks.

These are descriptive results for four repository-owned teaching fixtures. Shared warmups and Medusa's disclosed clock-seeded chooser randomness mean the slots are not independent samples. Goal reachability is not a claim about a production vulnerability.

## Per-fixture profile results

| Fixture | Profile | Goal hits | Runs | Mean observed end (s) | Mean charged end (s) | Reasons |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| bounded_ledger | b08-concrete | 2 | 10 | 6.010 | 6.229 | native_import_goal_reached: 2, no_candidate: 8 |
| bounded_ledger | b08-native | 0 | 10 | 6.007 | 6.259 | native_continuation_no_goal: 10 |
| bounded_ledger | b08-symbolic-q075 | 10 | 10 | 6.019 | 6.224 | native_import_goal_reached: 10 |
| bounded_ledger | b32-concrete | 2 | 10 | 30.010 | 30.870 | native_import_goal_reached: 2, no_candidate: 8 |
| bounded_ledger | b32-native | 0 | 10 | 30.008 | 30.893 | native_continuation_no_goal: 10 |
| bounded_ledger | b32-symbolic-q050 | 10 | 10 | 30.019 | 30.840 | native_import_goal_reached: 10 |
| bounded_ledger | b32-symbolic-q075 | 10 | 10 | 30.019 | 30.854 | native_import_goal_reached: 10 |
| bounded_ledger | b32-symbolic-q150 | 10 | 10 | 30.020 | 30.862 | native_import_goal_reached: 10 |
| phase_counter | b08-concrete | 3 | 10 | 6.015 | 6.270 | native_import_goal_reached: 3, no_candidate: 7 |
| phase_counter | b08-native | 0 | 10 | 6.022 | 6.287 | native_continuation_no_goal: 10 |
| phase_counter | b08-symbolic-q075 | 10 | 10 | 6.025 | 6.233 | native_import_goal_reached: 10 |
| phase_counter | b32-concrete | 3 | 10 | 30.016 | 31.045 | native_import_goal_reached: 3, no_candidate: 7 |
| phase_counter | b32-native | 0 | 10 | 30.019 | 31.061 | native_continuation_no_goal: 10 |
| phase_counter | b32-symbolic-q050 | 10 | 10 | 30.019 | 31.003 | native_import_goal_reached: 10 |
| phase_counter | b32-symbolic-q075 | 10 | 10 | 30.016 | 30.989 | native_import_goal_reached: 10 |
| phase_counter | b32-symbolic-q150 | 10 | 10 | 30.020 | 31.016 | native_import_goal_reached: 10 |
| range_gate | b08-concrete | 9 | 10 | 6.009 | 6.257 | native_continuation_goal_reached: 1, native_import_goal_reached: 5, no_eligible_prefix: 1, warmup_goal_reached: 3 |
| range_gate | b08-native | 10 | 10 | 6.002 | 6.235 | native_continuation_goal_reached: 7, warmup_goal_reached: 3 |
| range_gate | b08-symbolic-q075 | 10 | 10 | 6.015 | 6.229 | native_continuation_goal_reached: 2, native_import_goal_reached: 5, warmup_goal_reached: 3 |
| range_gate | b32-concrete | 10 | 10 | 30.014 | 30.931 | native_continuation_goal_reached: 2, native_import_goal_reached: 5, warmup_goal_reached: 3 |
| range_gate | b32-native | 10 | 10 | 30.002 | 30.888 | native_continuation_goal_reached: 7, warmup_goal_reached: 3 |
| range_gate | b32-symbolic-q050 | 10 | 10 | 30.013 | 30.878 | native_continuation_goal_reached: 2, native_import_goal_reached: 5, warmup_goal_reached: 3 |
| range_gate | b32-symbolic-q075 | 10 | 10 | 30.018 | 30.921 | native_continuation_goal_reached: 2, native_import_goal_reached: 5, warmup_goal_reached: 3 |
| range_gate | b32-symbolic-q150 | 10 | 10 | 30.014 | 30.901 | native_continuation_goal_reached: 2, native_import_goal_reached: 5, warmup_goal_reached: 3 |
| workflow_gate | b08-concrete | 8 | 10 | 6.020 | 6.194 | native_continuation_goal_reached: 1, native_import_goal_reached: 5, no_candidate: 1, no_eligible_prefix: 1, warmup_goal_reached: 2 |
| workflow_gate | b08-native | 7 | 10 | 6.012 | 6.197 | native_continuation_goal_reached: 5, native_continuation_no_goal: 3, warmup_goal_reached: 2 |
| workflow_gate | b08-symbolic-q075 | 9 | 10 | 6.022 | 6.184 | augmentation_timeout: 1, native_continuation_goal_reached: 2, native_import_goal_reached: 5, warmup_goal_reached: 2 |
| workflow_gate | b32-concrete | 10 | 10 | 30.023 | 30.548 | native_continuation_goal_reached: 3, native_import_goal_reached: 5, warmup_goal_reached: 2 |
| workflow_gate | b32-native | 10 | 10 | 30.017 | 30.568 | native_continuation_goal_reached: 8, warmup_goal_reached: 2 |
| workflow_gate | b32-symbolic-q050 | 10 | 10 | 30.025 | 30.537 | native_continuation_goal_reached: 2, native_import_goal_reached: 6, warmup_goal_reached: 2 |
| workflow_gate | b32-symbolic-q075 | 10 | 10 | 30.031 | 30.570 | native_continuation_goal_reached: 3, native_import_goal_reached: 5, warmup_goal_reached: 2 |
| workflow_gate | b32-symbolic-q150 | 10 | 10 | 30.021 | 30.520 | native_continuation_goal_reached: 3, native_import_goal_reached: 5, warmup_goal_reached: 2 |

## Interpretation boundary

The 8-second and 32-second settings support a paired two-level comparison only. The 0.50, 0.75, and 1.50 second values are whole Halmos goal-invocation process limits, not isolated SMT CPU time. Auxiliary concrete confirmations and goals observed by the subsequent native campaign are reported separately.

WorkflowGate rows retain no-prefix, timeout, no-candidate, and continuation-miss reasons separately. A negative row is not automatically attributed to symbolic solving cost.
