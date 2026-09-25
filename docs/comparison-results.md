# One-round comparator study

The one-round policy could use healing and defense that damage-only greedy ignored. It won every duel condition here, including one that MCTS did not finish within the 30-round limit. MCTS won more gauntlet and boss games. Random also beat the one-round policy in one gauntlet repeat and one boss repeat. The new baseline makes the comparison more demanding without establishing a universal ranking.

## Method and reproduction

The [protocol](comparison-protocol.json) was fixed before these outcomes. Each repeat used environment seeds 0 through 4 for every policy and scenario. The search seeds were 7, 42 and 99. Their corresponding policy seed ranges were 7 through 11, 42 through 46 and 99 through 103. Policy randomness is separate from the environment. MCTS starts a fresh search stream per scenario and continues it across that scenario's five games.

At each decision, the new policy enumerates legal actions and samples eight one-round successors per action. Every candidate starts from the same eight sample seeds, although its subsequent draw path can differ. It uses terminal results or the existing state heuristic. This decision algorithm does not use the search tree, but it shares the simulator and heuristic with MCTS. It is not independent ground truth.

MCTS receives 300 simulations per decision, a five-round horizon and a 60-second safety cap. All runs use one process. The comparator's successor transitions and MCTS simulations are different work units. One simulation can advance several rounds, so these are unequal compute budgets and do not support an efficiency claim.

```sh
python benchmark.py 5 --sims 300 --seed 7 --policy-seed 7 --one-round-samples 8 --json seed-7.json
python benchmark.py 5 --sims 300 --seed 42 --policy-seed 42 --one-round-samples 8 --json seed-42.json
python benchmark.py 5 --sims 300 --seed 99 --policy-seed 99 --one-round-samples 8 --json seed-99.json
python tools/render_comparison.py --check
```

The last command checks the committed report against the retained JSON. It does not run another experiment. The benchmark's legacy console intervals and z statistics are not used in this report.

## Every measured condition

Each entry reports clean wins out of five. These are paired repeated conditions over only five distinct environment seeds per scenario, not 15 independent trials. Greedy is deterministic and repeats the same outcomes. No confidence interval or significance claim is made.

| Scenario | Search / policy seed base | Random | Greedy | One round | MCTS |
|---|---|---|---|---|---|
| duel | 7 | 4/5 | 1/5 | 5/5 | 4/5 |
| gauntlet | 7 | 2/5 | 1/5 | 4/5 | 5/5 |
| boss | 7 | 0/5 | 0/5 | 0/5 | 3/5 |
| duel | 42 | 5/5 | 1/5 | 5/5 | 5/5 |
| gauntlet | 42 | 5/5 | 1/5 | 4/5 | 5/5 |
| boss | 42 | 0/5 | 0/5 | 0/5 | 3/5 |
| duel | 99 | 4/5 | 1/5 | 5/5 | 5/5 |
| gauntlet | 99 | 3/5 | 1/5 | 4/5 | 5/5 |
| boss | 99 | 1/5 | 0/5 | 0/5 | 3/5 |

Mean shaped score includes partial credit for unfinished games. It is not a win probability.

| Scenario | Seed base | Random | Greedy | One round | MCTS |
|---|---|---|---|---|---|
| duel | 7 | 0.9684 | 0.3320 | 1.0000 | 0.9927 |
| gauntlet | 7 | 0.5487 | 0.2000 | 0.9060 | 1.0000 |
| boss | 7 | 0.2044 | 0.0000 | 0.2365 | 0.6000 |
| duel | 42 | 1.0000 | 0.3320 | 1.0000 | 1.0000 |
| gauntlet | 42 | 1.0000 | 0.2000 | 0.9184 | 1.0000 |
| boss | 42 | 0.1174 | 0.0000 | 0.0868 | 0.8180 |
| duel | 99 | 0.9413 | 0.3320 | 1.0000 | 1.0000 |
| gauntlet | 99 | 0.6000 | 0.2000 | 0.9184 | 1.0000 |
| boss | 99 | 0.3022 | 0.0000 | 0.2267 | 0.7883 |

Average rounds to win, conditional on winning. A dash means no clean win, not zero rounds.

| Scenario | Seed base | Random | Greedy | One round | MCTS |
|---|---|---|---|---|---|
| duel | 7 | 21.75 | 16.00 | 20.80 | 17.50 |
| gauntlet | 7 | 23.50 | 18.00 | 19.25 | 19.80 |
| boss | 7 | - | - | - | 24.67 |
| duel | 42 | 24.40 | 16.00 | 21.40 | 17.20 |
| gauntlet | 42 | 21.20 | 18.00 | 20.00 | 18.20 |
| boss | 42 | - | - | - | 23.67 |
| duel | 99 | 25.00 | 16.00 | 21.40 | 16.20 |
| gauntlet | 99 | 24.33 | 18.00 | 19.00 | 21.00 |
| boss | 99 | 24.00 | - | - | 24.00 |

## Observed work

| Scenario | Seed base | One-round decisions | Successor transitions | MCTS decisions | MCTS simulations | Shortfalls |
|---|---|---|---|---|---|---|
| duel | 7 | 104 | 4720 | 100 | 30000 | 0 |
| gauntlet | 7 | 107 | 6632 | 99 | 29700 | 0 |
| boss | 7 | 141 | 8152 | 128 | 38400 | 0 |
| duel | 42 | 107 | 5152 | 86 | 25800 | 0 |
| gauntlet | 42 | 110 | 6600 | 91 | 27300 | 0 |
| boss | 42 | 137 | 7352 | 131 | 39300 | 0 |
| duel | 99 | 107 | 4800 | 81 | 24300 | 0 |
| gauntlet | 99 | 106 | 7048 | 105 | 31500 | 0 |
| boss | 99 | 141 | 8152 | 132 | 39600 | 0 |

The three sequential runs took 27.01 seconds inside the benchmark on Python 3.11.8, Windows-10-10.0.26200-SP0. This is an environment record, not a timed comparison between policies. Every observed MCTS decision reached its requested 300 simulations.

## Evidence and limits

[Retained JSON](comparison-results.json) includes every individual game, its environment and policy seed, score, terminal result and round count. It also retains the per-decision work counts, run settings and normalized decision-source hashes captured before evaluation. Hashes use UTF-8 text with LF newlines and no BOM, so checkout line endings do not change identity.

The five environment seeds are a small fixed sample. Search randomness continues between games and the repeats reuse those environments. Neither wins nor shaped scores establish calibrated uncertainty or general playing strength. Different actions can consume different environment draws even when the initial seeds match. Parallel search and larger budgets were not evaluated here. No policy parameters were tuned after these results.

The zero boss wins for the one-round policy and MCTS's unfinished duel remain in the record. A useful next experiment would test a predeclared set of new environment seeds with matched transition or elapsed-work accounting. The historical reports remain separate and unchanged.
