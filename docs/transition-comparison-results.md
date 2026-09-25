# Transition allowance comparison

This study gives MCTS and one-round action enumeration the same allowance of 300 forward simulator transitions per decision. Whole simulations and whole equal-action sweeps can leave different unused remainders. Random and damage-only greedy remain contextual controls with no sampled forward search.

## Method

The [protocol](transition-comparison-protocol.json) was declared before outcomes. The allowance is a bounded engineering choice, not a tuned value. MCTS uses a five-round horizon. The comparator evaluates one-round successors using the same starting random seed for every candidate in a sweep. Both use the existing simulator and heuristic, so neither is independent ground truth.

Environment seeds 200 through 204 are reused across policy/search seed bases 7, 42 and 99. These are five environments per scenario, not 15 independent trials. Policy and environment RNGs are separate. Search starts fresh for each scenario and continues across its five games. Different actions can consume different random draws even with the same initial seed.

```sh
python benchmark.py 5 --transitions 300 --seed 7 --policy-seed 7 --game-seed 200 --json seed-7.json
python benchmark.py 5 --transitions 300 --seed 42 --policy-seed 42 --game-seed 200 --json seed-42.json
python benchmark.py 5 --transitions 300 --seed 99 --policy-seed 99 --game-seed 200 --json seed-99.json
python tools/render_transition_comparison.py --check
```

The last command validates retained data and checks this report. It does not run the experiment. MCTS and one-round enumeration each have a 60-second safety cap per decision, checked between complete units. The cap is not a hard deadline.

## Every measured condition

Clean wins out of five. These descriptive counts carry no significance test, confidence interval or general ranking claim.

| Scenario | Seed base | Random | Greedy | One round | MCTS |
|---|---|---|---|---|---|
| duel | 7 | 5/5 | 3/5 | 3/5 | 5/5 |
| gauntlet | 7 | 3/5 | 1/5 | 4/5 | 5/5 |
| boss | 7 | 1/5 | 0/5 | 0/5 | 4/5 |
| duel | 42 | 4/5 | 3/5 | 4/5 | 5/5 |
| gauntlet | 42 | 3/5 | 1/5 | 5/5 | 5/5 |
| boss | 42 | 0/5 | 0/5 | 0/5 | 3/5 |
| duel | 99 | 5/5 | 3/5 | 4/5 | 5/5 |
| gauntlet | 99 | 4/5 | 1/5 | 4/5 | 5/5 |
| boss | 99 | 0/5 | 0/5 | 0/5 | 4/5 |

Mean shaped score includes partial credit and is not a win probability.

| Scenario | Seed base | Random | Greedy | One round | MCTS |
|---|---|---|---|---|---|
| duel | 7 | 1.0000 | 0.7850 | 0.7454 | 1.0000 |
| gauntlet | 7 | 0.7577 | 0.2990 | 0.8000 | 1.0000 |
| boss | 7 | 0.2000 | 0.0000 | 0.1172 | 0.8967 |
| duel | 42 | 0.9686 | 0.7850 | 0.8764 | 1.0000 |
| gauntlet | 42 | 0.6000 | 0.2990 | 1.0000 | 1.0000 |
| boss | 42 | 0.2208 | 0.0000 | 0.0458 | 0.7039 |
| duel | 99 | 1.0000 | 0.7850 | 0.8764 | 1.0000 |
| gauntlet | 99 | 0.8000 | 0.2990 | 0.8000 | 1.0000 |
| boss | 99 | 0.0000 | 0.0000 | 0.1163 | 0.8000 |

Average rounds conditional on a clean win. A dash means no win.

| Scenario | Seed base | Random | Greedy | One round | MCTS |
|---|---|---|---|---|---|
| duel | 7 | 21.4000 | 13.3333 | 15.0000 | 18.4000 |
| gauntlet | 7 | 25.6667 | 18.0000 | 22.2500 | 17.8000 |
| boss | 7 | 26.0000 | - | - | 24.7500 |
| duel | 42 | 20.2500 | 13.3333 | 16.0000 | 17.2000 |
| gauntlet | 42 | 24.0000 | 18.0000 | 20.6000 | 14.8000 |
| boss | 42 | - | - | - | 21.6667 |
| duel | 99 | 21.8000 | 13.3333 | 16.5000 | 18.4000 |
| gauntlet | 99 | 21.7500 | 18.0000 | 19.2500 | 19.2000 |
| boss | 99 | - | - | - | 23.0000 |

## Actual work and unfinished games

| Scenario | Seed base | Policy | Decisions | Used transitions | Unused allowance | Used min/max | Complete units | Time shortfalls |
|---|---|---|---|---|---|---|---|---|
| duel | 7 | one_round | 105 | 31192 | 308 | 294/300 | 4842 | 0 |
| duel | 7 | mcts | 92 | 27517 | 83 | 296/300 | 6196 | 0 |
| gauntlet | 7 | one_round | 109 | 32393 | 307 | 285/300 | 5686 | 0 |
| gauntlet | 7 | mcts | 89 | 26649 | 51 | 296/300 | 5957 | 0 |
| boss | 7 | one_round | 143 | 42386 | 514 | 294/300 | 5926 | 0 |
| boss | 7 | mcts | 129 | 38604 | 96 | 296/300 | 8333 | 0 |
| duel | 42 | one_round | 94 | 27940 | 260 | 294/300 | 4561 | 0 |
| duel | 42 | mcts | 86 | 25737 | 63 | 296/300 | 5841 | 0 |
| gauntlet | 42 | one_round | 103 | 30576 | 324 | 285/300 | 5077 | 0 |
| gauntlet | 42 | mcts | 74 | 22151 | 49 | 296/300 | 4633 | 0 |
| boss | 42 | one_round | 140 | 41504 | 496 | 294/300 | 5800 | 0 |
| boss | 42 | mcts | 120 | 35882 | 118 | 296/300 | 8887 | 0 |
| duel | 99 | one_round | 96 | 28554 | 246 | 294/300 | 4650 | 0 |
| duel | 99 | mcts | 92 | 27528 | 72 | 296/300 | 6058 | 0 |
| gauntlet | 99 | one_round | 95 | 28177 | 323 | 285/300 | 3643 | 0 |
| gauntlet | 99 | mcts | 96 | 28724 | 76 | 296/300 | 6672 | 0 |
| boss | 99 | one_round | 143 | 42386 | 514 | 294/300 | 5926 | 0 |
| boss | 99 | mcts | 113 | 33817 | 83 | 296/300 | 7900 | 0 |

Complete units mean MCTS simulations or comparator sweeps, respectively. MCTS reserves a whole horizon before another simulation. The comparator requires one transition for every legal candidate before another sweep. Unused remainders alone are not time shortfalls.

Recorded time shortfalls: 0. Every decision reached its ordinary allowance stop.

| Scenario | Seed base | Policy | Environment seed | Result | Rounds |
|---|---|---|---|---|---|
| duel | 7 | greedy | 202 | unfinished | 30 |
| duel | 7 | greedy | 204 | unfinished | 30 |
| duel | 7 | one_round | 201 | unfinished | 30 |
| duel | 7 | one_round | 202 | unfinished | 30 |
| gauntlet | 7 | random | 204 | unfinished | 30 |
| gauntlet | 7 | greedy | 200 | unfinished | 30 |
| boss | 7 | one_round | 201 | unfinished | 30 |
| boss | 7 | one_round | 203 | unfinished | 30 |
| boss | 7 | mcts | 204 | unfinished | 30 |
| duel | 42 | random | 201 | unfinished | 30 |
| duel | 42 | greedy | 202 | unfinished | 30 |
| duel | 42 | greedy | 204 | unfinished | 30 |
| duel | 42 | one_round | 202 | unfinished | 30 |
| gauntlet | 42 | greedy | 200 | unfinished | 30 |
| boss | 42 | random | 200 | unfinished | 30 |
| boss | 42 | random | 203 | unfinished | 30 |
| boss | 42 | one_round | 201 | unfinished | 30 |
| boss | 42 | mcts | 201 | unfinished | 30 |
| duel | 99 | greedy | 202 | unfinished | 30 |
| duel | 99 | greedy | 204 | unfinished | 30 |
| duel | 99 | one_round | 202 | unfinished | 30 |
| gauntlet | 99 | greedy | 200 | unfinished | 30 |
| boss | 99 | one_round | 201 | unfinished | 30 |
| boss | 99 | one_round | 203 | unfinished | 30 |

An unfinished game reached the 30-round limit. It is neither a clean win nor a loss. Every terminal loss and win is retained in the JSON as well.

## Evidence and limits

Evaluated source: `c25ad84a2d07259ec7c94ce99c4a6e623be18413`. The three serial runs took 9.31 seconds in the benchmark on Python 3.11.8, Windows-10-10.0.26200-SP0. This records the environment, not a policy speed comparison.

The [retained JSON](transition-comparison-results.json) keeps all 180 game records, actual seeds, terminal results, exact decision work, stop reasons and half-open decision ranges for each game. Source hashes use UTF-8 text with LF newlines and no BOM. The [earlier study](comparison-results.md) remains unchanged.

Equal transition allowances do not equalize CPU time, memory or cloning overhead. Total work also depends on game length and whole-unit remainders. The small fixed environment set and repeated conditions do not establish general playing strength. The new environment set also prevents treating this as a controlled before/after improvement over the earlier study.
