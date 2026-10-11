# Compare search allowances against the saved one-round objective

Use the existing installed engine and separate episode companion to inspect a
fixed 8-versus-64 simulation comparison, then repeat a decision from the same
saved state. The diagnostic measures the exact score loss of the selected
physical action under the existing independent one-round reference. It asks
whether more search work helped on these declared modeled states.

The four deciding cases had a pooled mean loss of approximately 0.01690538 at
8 simulations and 0.00428602 at 64. That is a reduction of approximately
0.01261936 score units, or 74.65 percent. Of the 64 deciding seed pairs, 22 had
lower loss at 64, 3 had higher loss and 39 had equal loss. Exact best-action
selection increased from 27 of 64 to 42 of 64. The exploratory E2 case was
adverse to the larger allowance and remains in the evidence.

These are finite-corpus results under one declared objective. They do not
establish stronger full-encounter play, a population effect, win probability or
a new default. The selector stays `mean_visits`, exploration stays 1.2, and
engine defaults and rewards remain unchanged. This comparison holds those
controls fixed. The separate [stability diagnostic](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-stability.md)
addresses variation across selectors, coefficients and seeds.

## Acquire and inspect the evidence

Follow [the companion installation journey](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-companion.md) to download
`episode-companion.zip`, check its SHA-256 sidecar, extract the whole companion
and install the matching engine. The wheel contains only `engine/`. This guide
and the evidence are in the separate companion. No development checkout is
needed.

The `docs/search-allowance/` directory contains:

| Files | What is retained |
| --- | --- |
| [cards.json](search-allowance/cards.json), [scenarios.json](search-allowance/scenarios.json) | Exact custom input bytes for all six cases |
| [protocol.json](search-allowance/protocol.json) | Frozen cases, controls, seed split, work limits and prospective deciding gate |
| [results.json](search-allowance/results.json) | All 144 cells' exact recommendations, losses, work and input hashes, six complete action-value tables, ties, outcome masses, paired results and the deciding gate |
| `E1.episode.json` through `D4.episode.json`, with corresponding `.replay.json` files | Six original captures and their completed environment replay reports |
| `{case}.seed-{seed}.sims-{8,64}.{decision,reference}.json` | Original decision/reference pairs for the first seed in each frozen list, 301 for E and 2001 for D |

The complete table covers all declared cells. The distribution includes 24
selected raw decision/reference documents. It does not include the other 264
raw documents. Their hashes remain in the table, and the full raw corpus is
retained in the private release evidence. This compact publication sample was
chosen deterministically after collection, using each case's first listed seed.
The first-seed reader checks were part of the frozen protocol. No raw capture
or selected report was rewritten for distribution. This evidence table is a static study artifact,
not a new input format for the engine or reference command.

Use PowerShell 7.4 or later for byte-preserving native stdout redirection.
Choose fresh output paths in an existing parent directory, keep stderr
separate and check `$LASTEXITCODE` after each command. Redirection can create
or overwrite a file even when the command fails. These examples use the
installation paths from the companion guide:

```powershell
$py = 'C:\work\engine-env\Scripts\python.exe'
$companion = 'C:\work\episode-companion'
$evidence = "$companion\docs\search-allowance"
& $py "$companion\inspect_episode.py" "$evidence\D1.episode.json" --appearance obscur > C:\work\D1-episode.html
& $py "$companion\reference_episode.py" "$evidence\D1.seed-2001.sims-8.reference.json" --inspect --appearance obscur > C:\work\D1-eight.html
& $py "$companion\reference_episode.py" "$evidence\D1.seed-2001.sims-8.reference.json" --inspect --compare-report "$evidence\D1.seed-2001.sims-64.reference.json" --appearance obscur > C:\work\D1-comparison.html
```

Open the completed HTML locally. These operations read saved documents without
replaying transitions, running search or computing new reference values. The
comparison displays exact action values, all physical ties, selected losses,
search settings, source identities and comparison eligibility. Inspecting a
saved report checks its admitted structure and arithmetic consistency. It
does not authenticate its author or independently recompute its model.

## Replay, then request a fresh decision

Environment replay applies the original actions and random stream without new
search. It requires the recorded implementation, runtime labels and exact
content bytes. A matching engine installation alone does not guarantee that a
different Python or platform can replay these original Windows captures.
Passive inspection has separate admission rules and can still read an admitted
report. Historical incompatibility remains visible.

```powershell
& $py "$companion\episode.py" replay "$evidence\D1.episode.json" --cards "$evidence\cards.json" --scenarios "$evidence\scenarios.json" > C:\work\D1-replay.json
```

Request two fresh decisions from the retained step-zero state. They use the
same seed and differ only in the simulation allowance. The command reads the
existing seven-card hand without refilling it or continuing the capture's
search random stream:

```powershell
& $py "$companion\decide_episode.py" "$evidence\D1.episode.json" --step 0 --seed 2001 --sims 8 --horizon 1 --exploration 1.2 --final-action-rule mean_visits > C:\work\D1-fresh-eight.json
& $py "$companion\decide_episode.py" "$evidence\D1.episode.json" --step 0 --seed 2001 --sims 64 --horizon 1 --exploration 1.2 --final-action-rule mean_visits > C:\work\D1-fresh-sixty-four.json
& $py "$companion\reference_episode.py" C:\work\D1-fresh-eight.json --model one-round --method physical --max-paths 100 --max-total-paths 800 --max-seconds 1 > C:\work\D1-fresh-eight-reference.json
& $py "$companion\reference_episode.py" C:\work\D1-fresh-sixty-four.json --model one-round --method physical --max-paths 100 --max-total-paths 800 --max-seconds 1 > C:\work\D1-fresh-sixty-four-reference.json
& $py "$companion\reference_episode.py" C:\work\D1-fresh-eight-reference.json --inspect --compare-report C:\work\D1-fresh-sixty-four-reference.json --appearance obscur > C:\work\D1-fresh-comparison.html
```

The fresh decision has its own observed installation/runtime identity. Read
its identity comparisons instead of assuming it equals a historical producer.
The recorder includes `demo.py` in its example identity, while the saved-state
decision records its `game/` helpers. Their example-file maps can differ by
role. That does not erase engine or runtime differences, and it does not change
the existing compatibility rules.

## Create another episode with the same custom inputs

This is the existing recording command. It uses the supplied scenario and
card definitions, one round, one capture simulation and explicit seeds:

```powershell
& $py "$companion\episode.py" record D1 --cards "$evidence\cards.json" --scenarios "$evidence\scenarios.json" --environment-seed 1103 --search-seed 0 --rounds 1 --sims 1 --horizon 1 > C:\work\D1-new-episode.json
& $py "$companion\episode.py" replay C:\work\D1-new-episode.json --cards "$evidence\cards.json" --scenarios "$evidence\scenarios.json" > C:\work\D1-new-replay.json
& $py "$companion\inspect_episode.py" C:\work\D1-new-episode.json --appearance obscur > C:\work\D1-new-episode.html
```

Use `decide_episode.py` and `reference_episode.py` as above to inspect new
search allowances from that new capture. A recreated document can differ from
the retained original because producer/runtime metadata changed. Preserve both
files and their source identities. The captured later outcome was not used to
choose the study cases, search controls or deciding gate.

## Repeat the declared comparison

The exploratory slice used E1/E2 with seeds 301 through 304. The deciding
slice used D1 through D4 with seeds 2001 through 2016, fixed before deciding
collection. Every seed was used at both 8 and 64 simulations. All cells used
step 0, horizon 1, serial clockless search, `mean_visits` and exploration 1.2,
without priors, parallel workers or a search time budget.

| Case | Slice | Player HP | Enemy HP | Enemy damage | Capture environment seed | Search seeds |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| E1 | Exploratory | 60 | 16 | 10 | 73 | 301..304 |
| E2 | Exploratory | 32 | 22 | 14 | 79 | 301..304 |
| D1 | Deciding | 80 | 18 | 12 | 1103 | 2001..2016 |
| D2 | Deciding | 24 | 18 | 12 | 1109 | 2001..2016 |
| D3 | Deciding | 80 | 24 | 20 | 1117 | 2001..2016 |
| D4 | Deciding | 24 | 24 | 20 | 1123 | 2001..2016 |

For the full repeat, use each original `{case}.episode.json` with every listed
seed at both allowances, then price every resulting decision using the explicit
physical-reference controls above. Do not select cases or seeds after inspecting
the repeated results. Compare complete raw reports to `results.json` using
their state, action, exact fraction, work and identity fields. A new raw hash
can differ when producer metadata differs. Hash equality is a byte-identity
claim, not a substitute for checking those fields.

The inputs give each root eight ordered physical actions: pass plus seven
card positions. Repeated copies of the same card stay separate actions. The
variable damage, fixed damage and shield alternatives have different expected
values. All admitted one-round outcomes remain ongoing. The smallest enemy HP
is 16 and the largest player hit is 10. The smallest player HP is 24 and the
largest enemy hit is 20. No terminal payoff is encountered in these cases.

The reference model is
`independent_one_round_binary53_shaped_v1`, with the original physical method.
It exactly weights source-order binary64 shaped payoffs under its declared
independent binary53 accuracy and inclusive integer-damage law. Its objective
matches horizon-one MCTS. The existing sampled one-round comparator has
different terminal win/loss values and is excluded. The reported loss is the
exact best action expectation minus the selected physical action expectation.
Stability of a recommendation is not the same quantity.

The prospective deciding gate requires all cells and consumer checks to
complete, at least two distinct exact action values per case, no larger mean
loss at 64 in any deciding case, a positive pooled baseline at 8, and a pooled
reduction of at least 25 percent and 0.005 score units. The four deciding cases
and their seed pairs have equal weight. Exploratory cells are retained but do
not enter this gate. Exact fractions and the evaluated conditions are in
`results.json`.

## Work, failures and delivery limits

Each search declares 8 or 64 simulations of one round. The reference is limited
to 100 physical leaves per action, 800 across the root and a one-second
cooperative calculation deadline. These bounds are explicit repeat controls,
not performance measurements. The cooperative deadline does not cap startup,
identity capture, input validation, output, memory or hard wall time. A consumer
needing process isolation must own external limits.

A refused or incomplete reference has no accepted evaluation or score loss.
Keep the refusal, stderr and exit status. It is not agreement or disagreement.
Invalid inputs exit 2, reference refusal/runtime failure exits 1, interruption
exits 130 and complete calculation or passive inspection exits 0. Original
episode replay incompatibility exits 3. See the existing
[reference limits](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-reference.md#supported-subset-and-limits) and
[record/replay contract](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-record-replay.md) for the full boundaries.

Private collection-helper qualification failures are retained separately from
the accepted corpus and accounted for in the public results. They are not
silently skipped cells or claims that the engine/reference was defective.
Successful episode replay establishes reproduction of saved transitions.
Reference agreement and independent mathematical review supply different
evidence. Neither proves correctness outside the declared model or these cases.

The companion retains its existing 128-member, 1 MiB-per-member and 8 MiB-total
payload limits. Static study evidence is explicitly listed in the existing
companion and Pages builders. The engine wheel and saved-episode reader kit are
unchanged. Study documents retain their original source declarations, while the
companion manifest and Pages presentation identify the delivery revision.
