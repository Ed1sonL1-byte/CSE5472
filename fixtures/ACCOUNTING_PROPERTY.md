# Stage 4 integer-accounting property

The two local contracts are inert counters with no assets, transfers, external calls, or environment-dependent behavior. `open()` grants 100 units once. `spend(amount)` should transfer an allowed amount from `remaining` to `spent` without changing `allocated`. Both contracts expose the same method signatures and start with all counters at zero.

The business safety property is `allocated == spent + remaining` after every call. The fourth value of `observe()` reports its negation for compatibility with the existing observer shape, but an acceptance or audit must recompute the equality from the three integer fields. `propertyHolds()` is a second on-chain read of the same formula. `invariantHolds()` is only a bounded structural check for execution consistency; its truth does not establish the business property.

The flawed contract's full-balance branch zeros `remaining` without incrementing `spent`. This is a bookkeeping omission on a natural operation boundary, `amount == remaining`. The repaired contract applies the ordinary debit and spent-credit updates for every allowed amount. Neither contract has a branch keyed to a solver value or a mutable goal flag.

The deterministic Foundry regression uses `open(); spend(100)` solely to establish ground truth. It must not be inserted into a formal warmup corpus, candidate dictionary, or solver output. Both versions also test partial spends `7` and `13`, an over-limit request, and an unopened request. Those values are regression examples, not formal experimental seeds.
