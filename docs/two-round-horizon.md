# Compare two horizons at the same completed transition count

The October 18, 2026 study is inconclusive under its declared uncertainty rule.
At 64 completed simulator transitions per search, horizon two had lower average
first-action loss on the six fixed deciding states. Its mean advantage was
`0.0292151` shaped-score units, with a conservative 95 percent interval of
`[-0.0548762, 0.1133064]`. That interval includes zero. Horizon one did better on
the near-completion state D3. The result does not select a new default.

The caller is the public `engine.MCTS` API on explicitly modeled roots. The
engineering decision was whether to spend this fixed transition allowance on
64 horizon-one simulations or 32 horizon-two simulations. This compares those
whole configurations. It does not isolate lookahead depth from simulation count
or the heuristic's scoring depth, and it does not compare elapsed CPU time.

## One target for both configurations

For each root action, the existing [adaptive reference](episode-adaptive-reference.md)
computes an exact two-round value `Q2(a)` under its qualified model. It fixes the
first action and chooses an optimal legal second action separately for each
complete first-round observation. The measured loss is
`max_a Q2(a) - Q2(selected physical root action)`. Zero means the selected action
belongs to the exact best-action tie set.

This endpoint prices a first choice assuming optimal observed-state continuation.
It does not estimate the search's actual second choice or full encounter return.
The reference preserves source-order binary64 shaped scoring and binary53
probability semantics. It is not a win-probability oracle. In particular, the
preserved objective can rank an ongoing near-completion state above a win.

The existing saved-decision quality route still requires horizon two. This
study supplies normalized states directly to the reference and explicitly joins
both searches' selected physical coordinates to the same complete action table.
It does not relabel a horizon-one saved report or weaken historical identity
admission. Identical card copies retain separate physical indices.

## Frozen cases, work and randomness

[The protocol](two-round-horizon/protocol.json),
[complete normalized inputs](two-round-horizon/inputs.json) and
[seed labels](two-round-horizon/seeds.json) were saved before collecting either
phase's outcomes. The private owner evidence retains their prospective hashes
and independent pre-run reviews. This is a local prospective record, not an
external preregistration or authenticated collection service.

Every root has three zero-cost cards: a variable hit of 1 through 3, a fixed hit
of 2 and a pure heal. D5 replaces the fixed hit with a second physical copy of
the variable hit. There is one plain enemy, no rules, effects or initial
modifiers, and no random pip gain. Enemy accuracy below is the attack accuracy,
separate from the model's enemy-attempt probability of 0.85.

| Case | Player HP / maximum | Enemy HP / maximum | Enemy hit | Accuracy | Heal |
| --- | --- | --- | --- | --- | --- |
| E1 | 7 / 16 | 5 / 12 | 1..2 | 0.75 | 3 |
| E2 | 16 / 16 | 5 / 100 | 1 | 0.75 | 3 |
| D1 | 5 / 20 | 4 / 8 | 1..3 | 0.75 | 5 |
| D2 | 10 / 20 | 5 / 10 | 1..3 | 0.75 | 5 |
| D3 | 20 / 20 | 4 / 100 | 1 | 0.75 | 5 |
| D4 | 10 / 20 | 6 / 12 | 1..2 | 1.0 | 5 |
| D5 | 7 / 16 | 5 / 10 | 1..3 | 0.75 | 4 |
| D6 | 6 / 12 | 4 / 8 | 1..2 | 0.5 | 3 |

These are new tuples within a familiar modeled family. They are not a random
sample of combat situations or a broad domain holdout. Ordinary episode capture
refills a seven-card hand, so this small reference subset uses public model
constructors rather than a fabricated captured episode.

Before any search, each complete reference must cover every root action and
every positive-mass first-round successor, with all those successors nonterminal.
This gate establishes one transition per horizon-one simulation and two per
horizon-two simulation. Each accepted search also independently counts actual
`advance_round` calls, checks the engine's counters, requires zero unused
transitions and verifies that its original root was unchanged. A failed gate
aborts the phase without replacing a state, seed or missing result.

Both configurations use ordinary UCT, exploration 1.2, the existing mean-then-
visits final ordering, no priors and no clock deadline. Every search receives a
fresh `random.Random(label)`. Labels were drawn independently with replacement
from the OS as 64-bit integers. The two configurations do not share an RNG or
matched simulator trajectories. The retained labels enable replay but cannot
authenticate their collection or guarantee disjoint PRNG streams.

Exploration used two cases, eight blocks and two configurations: 32 searches and
2,048 completed search transitions. The deciding phase used six cases, 256 blocks
and two configurations: 3,072 searches and 196,608 completed search transitions.
The adverse exploratory E2 result was retained. No cases, weights, seeds, budget
or stopping rule were changed after it. All admitted reference calculations and
all expected search cells completed in one attempt per phase.

## Deciding results

Lower loss is better. Each row averages the 256 frozen labels for that state and
configuration. The hit columns count exact optimal-tie membership, not wins.

| Case | Mean loss H1 | Mean loss H2 | Optimal hits H1 | Optimal hits H2 |
| --- | --- | --- | --- | --- |
| D1 | 0.0668764 | 0.0129669 | 98 | 119 |
| D2 | 0.0652148 | 0.0202946 | 4 | 96 |
| D3 | 0.0005630 | 0.0060799 | 142 | 60 |
| D4 | 0 | 6.754e-19 | 256 | 210 |
| D5 | 0.0614408 | 0.0135649 | 25 | 205 |
| D6 | 0.0359961 | 0.0018945 | 96 | 122 |

D3 is an adverse result for horizon two. D4's strict hit-count difference
corresponds to extremely small exact score gaps. Its loss remains visible as a
fraction in the data and contributes essentially no practical separation here.
Do not convert that hit-count difference into a substantial quality claim or
round the exact values into invented ties.

For each block, average `D = loss_H1 - loss_H2` equally across its six cases.
The 256 block contrasts, rather than 1,536 constituent case contrasts or
individual simulations, are the inferential units. There were 239 positive,
zero equal and 17 negative block contrasts. Their mean was `0.0292150688171387`
and unbiased sample variance was approximately `0.000443673113962033`.

The prespecified interval uses
`sqrt(2*s_squared*ln(80)/n) + 14*ln(80)/(3*(n-1))` as its radius, clipped to
`[-1,1]`. This follows [Maurer and Pontil, Theorem 4, page 2](https://arxiv.org/pdf/0907.3740)
by mapping `D` to `(D+1)/2`, applying both one-sided bounds with failure
probability 0.025 each and rescaling. The collector uses exact fractions and
conservative rational upper bounds for the logarithm and square root. Independent
Decimal arithmetic checks those bounds. At 256 blocks the additive term alone
is about 0.0802, so this design can leave a modest effect unresolved.

The interval is conditional on independently initialized seed-label experiments
on these six fixed states and this source. It is not uncertainty over a
population of scenarios. Its endpoints include zero, giving the declared
inconclusive disposition. Sample means and adverse cases remain informative
descriptions without selecting a default or requesting more deciding samples.

## Inspect and reproduce

[Exploratory data](two-round-horizon/exploratory.json) and
[deciding data](two-round-horizon/deciding.json) retain all selected actions and
exact losses, complete root value tables, block contrasts, source maps and work
totals. `cell_columns` names the compact cell-array columns. Seed labels are in
the separate frozen file. Every row had 64 reported and independently counted
transitions, with 64 simulations for H1 and 32 for H2.

The compact files are projections of retained full output. Their `full_results`
and `reference_reports` fields identify the original bytes. The private owner
evidence retains full root statistics, append-only cell logs, complete reference
observations and attempt records. Hashes bind content and do not authenticate
execution. The collector reproduces full outputs, including those omitted
statistics and reference observations, from the supplied inputs.

Use Python 3.11 or later and the separately installed matching engine plus the
whole [companion](episode-companion.md#acquire-both-parts). These PowerShell
examples assume `$py`, `$companion` and an existing `C:\work` parent. Output
directories must be fresh. Check `$LASTEXITCODE` and retain stderr.

```powershell
& $py "$companion\tools\two_round_horizon_study.py" --phase exploratory --output C:\work\horizon-exploratory
& $py "$companion\tools\two_round_horizon_study.py" --phase deciding --output C:\work\horizon-deciding
```

These commands actively compute references and run serial search. They are not
passive inspection. The original collection used an outer 120-second timeout for
each phase. The command itself does not impose that hard wall bound or a memory
cap. Each reference has cooperative limits of 10,000 transition leaves, 2,500
per root action, 25,000 work units and 10 seconds. Original roots and frozen
inputs are rechecked after collection. A failed or interrupted attempt is not a
complete result. Forced interpreter termination may leave no final receipt.

The original collection used CPython 3.11.8 on Windows, source baseline
`3797838079eab49b1f627293239acc322079023a`. The retained implementation maps
identify the model, search and reference bytes. Reproduction on another runtime
records its actual identity. Compare admitted actions, exact losses and work,
rather than assuming all environment and producer metadata must hash equally.
An external installed-consumer witness repeats only E1's first two search cells
and its reference to check delivery, not the deciding study.

## Research and interpretation boundaries

[Phan, Chan and Koenig, AAAI 2025](https://ojs.aaai.org/index.php/AAAI/article/view/34867)
discuss open-loop planning's information pattern and limited search resources.
[Lecarpentier and colleagues, IJCAI 2018](https://www.ijcai.org/proceedings/2018/327)
study reusing and executing tree-search plans. Their settings and guarantees do
not establish this engine's quality. Their CORAL and tree-reuse algorithms are
not implemented here. Consensus helped locate those papers, followed by reading
the primary introductions and backgrounds. The statistical primary source was
read for the actual theorem and variance definition.

This study changes no engine, reward, reference model, source-admission rule,
action order or default. Earlier horizon-four stability, one-round allowance,
root-allocation and full-encounter studies answer different questions. PR59's
inconclusive encounter result remains intact. No Windows-versus-Linux workload,
hostile-code sandbox, GPU result or professional security experience follows
from this experiment.
