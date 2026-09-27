# Same forest, different execution

[Interactive report](https://t92t1914.github.io/mcts-combat-engine/same-forest.html) | [Raw results](same-forest-results.json) | [Declared protocol](same-forest-protocol.json) | [Earlier process study](parallel-scaling-results.md)

All 18 executions completed. In each of the six conditions, sequential execution and both process modes returned exactly the same worker seeds, work accounting, stopping reasons, raw root statistics and ranked actions. Each execution spent 12,000 simulations and 60,000 simulator transitions, with no unused allowance.

This control holds the forest fixed while changing how its roots execute. It separates execution timing from the change in search structure caused by dividing work among a different number of trees. Two roots and four roots remain different forests. This is not a playing strength study.

## Timing of identical forests

On narrow screens, scroll each table sideways for the remaining columns. Tab to a table and use the arrow keys when browsing by keyboard.

Each row is one condition with one observation per execution mode. A ratio divides sequential wall time by process wall time for that same forest. Ratios above one mean the process execution was faster in this observation. They are not confidence intervals or a general scaling claim. Some warm ratios exceed the root count. Uncontrolled ordinary machine activity and one observation cannot establish superlinear scaling.

Observed wall seconds and ratios

| Scenario | Roots | Sequential s | Cold s | Warm s | Sequential / cold | Sequential / warm |
| --- | --- | --- | --- | --- | --- | --- |
| duel | 2 | 1.109563 | 0.809045 | 0.577712 | 1.371 | 1.921 |
| duel | 4 | 1.316565 | 0.512314 | 0.305295 | 2.570 | 4.312 |
| gauntlet | 2 | 1.831624 | 1.054769 | 0.807727 | 1.737 | 2.268 |
| gauntlet | 4 | 1.789601 | 0.633350 | 0.442468 | 2.826 | 4.045 |
| boss | 2 | 1.192384 | 0.759412 | 0.794376 | 1.570 | 1.501 |
| boss | 4 | 1.133148 | 0.539349 | 0.310930 | 2.101 | 3.644 |

With two Boss roots, warm execution took 0.794376 seconds while cold execution took 0.759412 seconds. That slower warm observation is retained. The control does not explain its cause or justify assuming warm execution is always faster.

## What warm includes

Sequential and cold wall time include engine construction and the search call. Warm initializes a fresh engine and process pool before starting the search timer. No unrecorded search warms that pool. This differs from the earlier process study, where warm meant a second search on a reused pool. Every execution here builds fresh trees. Cleanup occurs outside the search timer.

Warm preparation and its contained pool startup are listed separately. Do not add both values as independent costs. Cold startup is already inside cold wall time. Longest root reports a component of computation, not an additional cost. These observations include scheduling and orchestration effects and do not isolate pure IPC latency.

Preparation and timing components in seconds

| Scenario | Roots | Mode | Preparation s | Prepared startup s | Startup in search s | Longest root s |
| --- | --- | --- | --- | --- | --- | --- |
| duel | 2 | sequential | 0.000000 | 0.000000 | 0.000000 | 0.558335 |
| duel | 2 | cold | 0.000000 | 0.000000 | 0.185209 | 0.620584 |
| duel | 2 | warm | 0.159176 | 0.159013 | 0.000000 | 0.576915 |
| duel | 4 | cold | 0.000000 | 0.000000 | 0.191731 | 0.319596 |
| duel | 4 | warm | 0.187320 | 0.187164 | 0.000000 | 0.304601 |
| duel | 4 | sequential | 0.000000 | 0.000000 | 0.000000 | 0.349398 |
| gauntlet | 2 | warm | 0.181824 | 0.181665 | 0.000000 | 0.807000 |
| gauntlet | 2 | sequential | 0.000000 | 0.000000 | 0.000000 | 0.963577 |
| gauntlet | 2 | cold | 0.000000 | 0.000000 | 0.184117 | 0.869519 |
| gauntlet | 4 | sequential | 0.000000 | 0.000000 | 0.000000 | 0.459809 |
| gauntlet | 4 | warm | 0.191744 | 0.191553 | 0.000000 | 0.441631 |
| gauntlet | 4 | cold | 0.000000 | 0.000000 | 0.194706 | 0.437892 |
| boss | 2 | warm | 0.169218 | 0.169062 | 0.000000 | 0.793769 |
| boss | 2 | cold | 0.000000 | 0.000000 | 0.160949 | 0.597706 |
| boss | 2 | sequential | 0.000000 | 0.000000 | 0.000000 | 0.597263 |
| boss | 4 | cold | 0.000000 | 0.000000 | 0.211925 | 0.326565 |
| boss | 4 | sequential | 0.000000 | 0.000000 | 0.000000 | 0.318758 |
| boss | 4 | warm | 0.183892 | 0.183729 | 0.000000 | 0.310210 |

## Identity and work accounting

The same WorkerJob allocation, seed derivation, fixed search, receipt validation and raw statistic merge serve every mode. Sequential execution uses the configured number of independent roots locally. It does not substitute one larger tree. Root seeds derive from search seed 42 and stable worker IDs. Raw visits and value sums merge in worker ID order.

All six comparisons match after removing only report and worker durations and pool startup. Every worker stopped at both the simulation cap and transition allowance. No execution failed or left unknown work. The retained JSON contains all receipts, action identities and means. Its compatibility field win_rate is mean shaped reward, not a calibrated win probability. The report validator reconstructs that mean from raw sums.

All 18 execution receipts

| Scenario | Roots | Mode | Simulations | Transitions | Unused simulations | Unused transitions |
| --- | --- | --- | --- | --- | --- | --- |
| duel | 2 | sequential | 12000 | 60000 | 0 | 0 |
| duel | 2 | cold | 12000 | 60000 | 0 | 0 |
| duel | 2 | warm | 12000 | 60000 | 0 | 0 |
| duel | 4 | cold | 12000 | 60000 | 0 | 0 |
| duel | 4 | warm | 12000 | 60000 | 0 | 0 |
| duel | 4 | sequential | 12000 | 60000 | 0 | 0 |
| gauntlet | 2 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 2 | sequential | 12000 | 60000 | 0 | 0 |
| gauntlet | 2 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 4 | sequential | 12000 | 60000 | 0 | 0 |
| gauntlet | 4 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 4 | cold | 12000 | 60000 | 0 | 0 |
| boss | 2 | warm | 12000 | 60000 | 0 | 0 |
| boss | 2 | cold | 12000 | 60000 | 0 | 0 |
| boss | 2 | sequential | 12000 | 60000 | 0 | 0 |
| boss | 4 | cold | 12000 | 60000 | 0 | 0 |
| boss | 4 | sequential | 12000 | 60000 | 0 | 0 |
| boss | 4 | warm | 12000 | 60000 | 0 | 0 |

## Protocol, chronology and limits

This follow up was designed after the completed 54 cell process study. The literature review below informed this new execution control, not that earlier protocol. Its six execution orders were fixed before measurement, with each mode twice in each ordinal position. It uses environment seed 300, search seed 42, horizon five and no priors. Each ordinary scenario starts with seven player pips and otherwise retains its defaults.

Measured source: 3adf64e618c277721d7ea36629cc934d0145a3ac. Implementation and protocol were committed and reviewed before this first attempt. Source identity remained unchanged during collection. The report and website are later presentations of retained measurements, not new experiments.

Shared Windows workstation. Only competing owned agent tests, rendering and measurements paused after coordination. Ordinary user applications and system settings left untouched. No exclusive machine access claimed.

Python: 3.11.8 (tags/v3.11.8:db85d51, Feb  6 2024, 22:03:32) [MSC v.1937 64 bit (AMD64)]. Platform: Windows-10-10.0.26200-SP0. Started: 2026-09-27T09:41:05.048271+00:00. Ended: 2026-09-27T09:41:22.344743+00:00.

One search seed, three initial states, two forest sizes and one observation per mode on one machine do not establish general speedup, cross platform performance or statistical significance. No episodes, quality comparison or parameter tuning followed the outcomes. Earlier studies and their unfavorable results remain unchanged.

## Subsequent method context

[Fern and Lewis, Ensemble Monte Carlo Planning](https://eecs.oregonstate.edu/~afern/papers/icaps11_uct.pdf). Sections 3.2, 3.3 and 5 distinguish ensemble size, trajectories per tree and sequential versus parallel comparisons. Their results do not establish stronger play or faster execution in this implementation.

[Steinmetz and Gini, author manuscript on parallel search](https://www-users.cse.umn.edu/~gini/publications/papers/Steinmetz2020TG.pdf). Sections II.C, III and V compare independent root trees with other parallel search arrangements in Go. Separate machines, time allowances and majority voting differ from this control's fixed total work and pooled raw statistics.

Validate and render these retained data without executing a search:

```sh
python tools/render_same_forest.py --check
```
