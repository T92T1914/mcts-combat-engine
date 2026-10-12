# Root allocation at a fixed search allowance

Use the existing saved-state decision command to select the optional
`sequential_halving` root policy. It makes a new horizon-one decision, records
the actual sampling stages and final-selection rule, and works with the existing
passive inspector, comparison and one-round reference. The ordinary UCT default,
recording policy and historical reports keep their original behavior.

## Run through the separate companion

Acquire the manifest-matched engine and the complete
[episode companion](episode-companion.md). The wheel contains only `engine/`.
Run these commands with that environment's Python from the extracted companion.
Choose fresh output filenames and check each exit status before using its output.
PowerShell 7.4 or later preserves native stdout bytes. The existing guides explain
POSIX redirection, earlier PowerShell encoding and command status meanings.

This example reuses the bundled custom D3 content. D3 was exposed exploratory
material for the new study. These commands demonstrate the consumer and do not
rerun or independently prove the sixteen-state deciding result.

```powershell
python episode.py record D3 --cards docs/search-allowance/cards.json --scenarios docs/search-allowance/scenarios.json --rounds 1 --sims 2 --horizon 1 > episode.json
python episode.py replay episode.json --cards docs/search-allowance/cards.json --scenarios docs/search-allowance/scenarios.json > replay.json
python decide_episode.py episode.json --step 0 --seed 19 --sims 32 --horizon 1 > uct.json
python decide_episode.py episode.json --step 0 --seed 23 --sims 32 --horizon 1 --root-allocation sequential_halving > halving.json
python inspect_episode.py halving.json --decision-report --appearance obscur > halving.html
python inspect_episode.py uct.json --decision-report --compare-report halving.json --appearance obscur > allocation-comparison.html
python reference_episode.py halving.json > halving-reference.json
python reference_episode.py halving-reference.json --inspect --appearance obscur > halving-reference.html
```

Fresh decisions reconstruct the saved pre-action state once. They do not refill
its hand, replay its environment or reuse the recording's advanced search stream.
The reference prices the saved recommendation without search. The HTML readers
perform no search, replay or reference calculation. Comparison exposes different
sampling settings and saved values. A single pair is not a statistical quality
comparison, and seed labels do not establish matched trajectories.

The new option requires `--horizon 1`, coefficient 1.2, no priors, serial execution
and no clock deadline. Omit `--exploration` or explicitly use 1.2. It cannot be
combined with `--stability`, `--extract-cell` or `--final-action-rule`.
The usual 0..64 simulation admission remains. Unsupported controls refuse before
search rather than being silently ignored. Work counts bound simulations and
transitions, not command time, memory or accuracy.

Core callers may select
`MCTS(horizon_rounds=1, max_sims=32, max_transitions=32, root_allocation="sequential_halving", rng=random.Random(23)).search(state, time_budget_ms=None)`.
The managed recording factory and parallel search retain their existing interfaces.
This first optional mode does not add a parallel allocation implementation.

## What changes

Ordinary UCT first covers untried root edges and then uses the current exploration
rule. The candidate is a budget-aware sequential-halving variant. It samples active
root actions in canonical physical order, discards the lower half by phase-local
sampled mean, and spends the remaining allowance on the survivors. Duplicate card
slots and separate targets remain separate actions. Pass remains an action.

For active count K, its minimum complete elimination allowance is the sum of
K, ceil(K/2), and successive survivor counts down to two. Below that allowance it
uses uniform round-robin coverage without elimination. Otherwise each phase uses
`q = max(1, floor(remaining_allowance / (remaining_rounds * active_count)))`
samples per active arm. Sampled-mean ties retain canonical physical order. Remaining
samples after one survivor all go to it. There are no hidden initialization draws.

A completed halving winner ranks first. Every other sampled action remains in the
report, ordered by cumulative raw mean, visits and canonical physical order. The
fallback uses that latter rule for all sampled actions. Unvisited actions have zero
visits/sum and a null mean. This final treatment is part of the candidate. The study
does not isolate allocation while keeping every selection/tie rule identical.

The simulator, reward objective, rollout and deeper-tree code are unchanged. The
new mode is restricted to horizon one. It changes the sampling policy and random
trajectory. It is not the earlier same-trajectory action-reuse optimization.

The method is motivated by [Karnin, Koren and Somekh's sequential-halving method](https://proceedings.mlr.press/v28/karnin13.pdf).
Its budget schedule and explicit tiny-budget fallback are this implementation's
contract. No published bandit guarantee is claimed for arbitrary adaptive trees
or for this finite-corpus result.

## Read the new report

Selecting this mode emits decision schema 3. Omission retains schema 1 or the
existing explicit-control schema 2. Version 3 records its sampling policy,
`survivor_mean_visits` final treatment, canonical tie rule and `root_allocation`
diagnostics. Its phases retain active physical coordinates, quota, completed
samples, phase-local sums/means and survivors. The report also retains the original
raw cumulative action statistics and actual simulations/transitions.

The passive validator checks the declared schedule, phase eliminations, remainder,
winner, action inventory and final ranking. It does not regroup phase sums to demand
bitwise equality with a differently accumulated raw sum. No epsilon defines a tie.
Schema 3 cannot be relabeled as an ordinary mean-first report or passively extracted
as a stability cell. The old versions remain readable and keep their own semantics.

Zero requested work gives a complete no-work report with no search, RNG or transition.
An interrupted core search retains partial accounting with `complete=false`.
A failed companion decision does not publish an apparently complete schema 3 result.
Saved hashes identify bytes and do not authenticate execution.

## Frozen deciding evidence

The question was whether one root-specific treatment could reduce first-action
reference loss at the same 32 completed simulations and transitions. Six previously
published roots were used only for exploratory diagnosis. The protocol, new
sixteen-state corpus, work accounting, seed namespaces, metrics, uncertainty and
promotion criteria were frozen before any deciding search.

Each of sixteen prospective controlled modeled states received 4,096 independently
initialized runs per policy. Each decision completed 32 horizon-one simulations and
32 transitions. All 131,072 deciding searches completed, totaling 4,194,304
simulations and transitions across both policies. No deciding case or adverse
secondary result was discarded. There was one candidate, no deciding-data tuning,
no selector/coefficient/budget sweep and no optional sample extension.

The existing independent `independent_one_round_binary53_shaped_v1` reference
priced every physical action. Loss is exactly `max(Q_ref) - Q_ref(selected)`.
The reference computes rational expectations of source-order binary64 shaped
payoffs under its declared iid binary53 and inclusive integer draw law. It is an
evaluation-only oracle and supplies no values to search.

| Four-state family | Baseline mean loss | Candidate mean loss | Baseline exact-best hits | Candidate exact-best hits |
| --- | ---: | ---: | ---: | ---: |
| Duel ongoing variance | 0.004663096837 | 0.002222579472 | 9,035 / 16,384 | 12,240 / 16,384 |
| Duel kill threshold | 0.024016457075 | 0.015579218238 | 10,930 / 16,384 | 12,324 / 16,384 |
| Two-enemy asymmetric response | 0.007665802382 | 0.001382902310 | 13,000 / 16,384 | 15,762 / 16,384 |
| Two-enemy area and target duplicates | 0.007613236682 | 0.001379842551 | 13,852 / 16,384 | 15,943 / 16,384 |

Equal-case mean loss fell from approximately 0.010989648244 to 0.005141135643.
The observed reduction was 0.005848512601, or 53.2184%. The pooled benefit interval
was [0.003370005242, 0.008327019960]. This met the frozen observed absolute 0.005
and relative 25% criteria, positive pooled lower bound and simultaneous per-state
harm-upper guard of 0.01. The largest harm upper bound was 0.008445570350 at NEW-KT1.

That lower pooled bound is below 0.005. The practical magnitude criteria concern
the observed estimate, not confidence-certified benefit of at least 0.005 or 25%.
All sixteen point mean losses improved, while five per-state harm intervals include
zero. Strict improvement in every state's underlying mean is not established.

Two exact-best hit rates were adverse:

| Case | Baseline hits | Candidate hits | Baseline mean loss | Candidate mean loss |
| --- | ---: | ---: | ---: | ---: |
| NEW-KT1 | 3,732 / 4,096 | 3,543 / 4,096 | 0.019517425725 | 0.015384439539 |
| NEW-KT4 | 4,033 / 4,096 | 3,935 / 4,096 | 0.002678985596 | 0.002664800573 |

Those histograms contain more near misses and fewer larger mistakes. Lower mean
loss does not establish better exact-best frequency in every case.

## Uncertainty, accounting and retained data

The pooled interval uses the frozen bounded-loss Hoeffding calculation. Simultaneous
per-policy/state bounds use [Maurer and Pontil's empirical-Bernstein result, Theorem 4](https://arxiv.org/pdf/0907.3740),
64 one-sided events and the declared union bound. The two error allocations total
0.05 under the declared independent Monte Carlo replication model. Distinct
hash-initialized PRNG streams are an assumption for that inference, not a proof of
random sampling. These are intervals for seed variation on fixed states, not a
population interval over encounters. Individual simulation rewards are not the
decision-loss replications.

Exact rational loss moments were independently recomputed from the saved physical
action histograms. A separately authored checker joined every row, seed label, input,
source, reference, completeness marker, transport and worker-retirement receipt.
It bounded logarithms by rational series and square roots by integer arithmetic,
separately checking the summary's outward intervals without a tie epsilon.

Candidate arithmetic counters across all deciding runs record 2,097,152 selections
and reward updates, 229,376 elimination rounds, 1,196,032 elimination sort-key
evaluations and 16,384 winner remainder samples. All first coverage and remainder
samples are included in the existing simulation/transition counts. These counters
are distinct work units, not machine instruction counts, equal CPU time or a speedup.

Read the [complete per-state results and histograms](root-allocation/results.json),
[sixteen modeled inputs](root-allocation/inputs.json),
[frozen protocol](root-allocation/protocol.json) and
[candidate contract](root-allocation/candidate-contract.json). Public JSON is a
serialized derivative of the accepted private qualification. The results retain
original freeze and raw-row hashes separately from public-file identity. The
original private raw rows and owned-operation receipts remain retained.

The baseline source was `825496207b3f8e5a0db3da65fb6d946238627e9c`.
The frozen candidate `engine/mcts.py` SHA256 was
`9be3ddafc78bbb617b232f733bc5dc7932b02ebafdd5d205273f604269af2c12`,
with every other engine body unchanged. That evaluated body uses CRLF. Git's
literal committed LF body has SHA256
`153e0c6b2f1b5ab1baeb92496ec19860b97b48008b177ce924c134d190cbf0f8`.
The exact CRLF-to-LF conversion was independently qualified against the retained
body and syntax tree. Both complete source maps are explicit. Arbitrary edited
or normalized sources remain unqualified. The deciding experiment used the
original private source-qualified body. Installed companion, CI and public delivery checks qualify
the subsequently delivered consumer separately. They do not relabel the study as
an installed experiment or establish a universal speed/quality claim.

The evidence supports this optional treatment on the admitted finite question.
The default remains unchanged. Arbitrary budgets, deeper horizons, modifiers,
boss rules, full-encounter outcomes, calibrated win probabilities and general
optimal play were not established by this study.
