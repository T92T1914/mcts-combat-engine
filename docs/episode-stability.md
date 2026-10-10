# How stable is a saved-state decision?

The installed engine and separate episode companion can repeat a bounded
decision across search seeds and exploration coefficients. The report compares
the existing mean-first recommendation with a visits-first choice from the same
statistics. It shows sensitivity, not stronger decisions or optimality.

Use the existing [companion acquisition](episode-companion.md) instructions.
Keep the complete companion together. No Git, development checkout, additional
reader or browser service is needed. The engine wheel still contains only
`engine/`.

## Compute, extract and inspect

Choose an existing ongoing pre-action step. `$py` and `$companion` are the
installed Python and extracted companion paths from the acquisition guide.
Use fresh output names, keep stderr separate and check `$LASTEXITCODE` after
each command. PowerShell 7.4+ preserves native stdout bytes; older Windows
PowerShell can transcode them.

```powershell
& $py "$companion\decide_episode.py" C:\records\episode.json --step 0 --stability --seeds 101 102 103 --explorations 0.6 1.2 2.4 --horizon 4 > C:\records\stability.json
& $py "$companion\decide_episode.py" C:\records\stability.json --extract-cell 0 --final-action-rule mean_visits > C:\records\mean.json
& $py "$companion\decide_episode.py" C:\records\stability.json --extract-cell 0 --final-action-rule visits_mean > C:\records\visits.json
& $py "$companion\inspect_episode.py" C:\records\visits.json --decision-report --appearance obscur > C:\records\visits.html
& $py "$companion\inspect_episode.py" C:\records\mean.json --decision-report --compare-report C:\records\visits.json > C:\records\selection.html
```

The sweep captures and validates the episode once. Each cell reconstructs the
same physical state, creates a new search RNG and runs exactly 64 simulations.
It does not replay earlier rounds, refill cards or continue the recording's
search stream. Horizon is 1..8, default four. The coefficient set is a unique
subset of `0.6,1.2,2.4`, default all three. This half/current/double grid measures
sensitivity on the unchanged shaped-reward scale, not an optimal constant.

Supply 2..16 signed 64-bit seed labels with distinct absolute values. Opposite
integer signs initialize the same Python RNG stream, so `7` and `-7` cannot
count as separate runs. Ordinary single decisions retain signed-seed acceptance.
Cells follow supplied coefficient order, then supplied seed order. Cell indices
are zero based. The maximum sweep is 48 serial calls, 3,072 simulations and
24,576 round transitions. There are no priors, workers or time-based search
deadlines. These bounds concern work counts, not wall time, memory or accuracy.

## Meaning and saved reports

`mean_visits` sorts sampled actions by mean shaped reward, then visits.
`visits_mean` sorts the same actions by visits, then mean. Both retain captured
root encounter order for complete ties. Physical card/target indices remain
identities even for duplicate names. Unvisited choices remain unvisited.

Each cell stores a validated schema 2 mean-first decision. Both diagnostic
rankings use that one captured search. Changed coefficients require separate
searches. Matching seed labels across coefficients do not guarantee identical
trajectories or identical random-stream consumption.

The JSON reports constituent decisions, requested/completed work, action
frequencies, modal counts, unordered seed-pair disagreements, same-stat selector
disagreement, exact leading primary/full tie counts, leading gaps, and matched
seed coefficient differences. Tie counts include the chosen action. Gaps are
null with fewer than two sampled choices. Visit gaps can be negative in
mean-first order; mean gaps can be negative in visits-first order.

The seed-pair denominator is `n*(n-1)/2`. Overlapping pairs are dependent
descriptive comparisons, not an independent-trial confidence sample. Shaped
rewards are not calibrated win probabilities. No policy-quality evaluation runs.

Extraction passively admits the saved grid, shared state and producer identity,
all constituents and recomputed diagnostics. It emits one ordinary schema 2
decision with explicit selector/derivation. Extraction, inspection and comparison
perform no search. The extracted decision's `search_performed`, counters and
producer identity describe its original cell. `derivation.new_search_performed`
is false and identifies captured sweep bytes/hash/status. Hashes compare bytes,
not authenticated origin or proof that the reported search occurred.

## Failure and resource boundary

| Exit | Meaning |
| --- | --- |
| 0 | Complete sweep or complete passive extraction |
| 2 | Argument, record, selected-state or saved-report refusal |
| 1 | Runtime/output failure or explicitly incomplete failed sweep |
| 130 | Interruption, including an explicitly incomplete interrupted sweep |

A failure after admission retains the completed cell prefix, identifies its
next unfinished cell or finalization stage and sets `status=incomplete`.
Finalization requires every declared cell to have completed. An interruption
immediately after a cell is committed retains that cell. Complete diagnostics
are null. Work totals describe completed admitted constituents;
an unfinished cell can have performed additional work without a complete report.
There is no retry, imputation or partial-success claim. A completed cell can
still be extracted with its incomplete source status preserved. An unfinished
cell cannot be extracted.

Captured/generated JSON is limited to 8 MiB, sixteen container levels and
200,000 aggregate values. Repeated fixed payload and maximum choices are
preflighted before search; final byte and schema admission remain mandatory.
A large state or identity can exceed the report cap even with a small grid.
No constituent is silently omitted. Current identity is observed before work
and checked during reporting. A changed source refuses completion.

Input/preflight failures leave JSON stdout empty. Complete or incomplete output
is buffered before writing. A write/flush failure can leave unusable partial
bytes. Redirection can overwrite a target on failure and is not atomic or durable
publication. The original input is never rewritten.

## Retained baseline

The [frozen protocol](stability/protocol.json) preceded deciding results at
source `986bc2fd503783368eb84f67bdc50e6957709441`. It selected duel, gauntlet and
boss initial states at environment seed 7 with search seeds 101..108, then
reserved states at environment seed 31 with search seeds 1001..1016. Each
cell used 64 simulations, horizon four and coefficients 0.6/1.2/2.4. Both slices
completed on 2026-10-10: 216 calls, 13,824 simulations and 55,296 transitions,
with no failed cell or unused allowance. These are scoped sensitivity
measurements of six early states, not a sampled workload or quality test.

| Slice/state | Coefficient | Mean-first seed-pair differences | Visits-first seed-pair differences | Same-stat selector differences |
| --- | ---: | ---: | ---: | ---: |
| Exploratory duel | 0.6 | 0/28 | 0/28 | 0/8 |
| Exploratory duel | 1.2 | 7/28 | 7/28 | 0/8 |
| Exploratory duel | 2.4 | 7/28 | 7/28 | 0/8 |
| Exploratory gauntlet | 0.6 | 23/28 | 25/28 | 2/8 |
| Exploratory gauntlet | 1.2 | 17/28 | 12/28 | 2/8 |
| Exploratory gauntlet | 2.4 | 17/28 | 12/28 | 2/8 |
| Exploratory boss | 0.6 | 7/28 | 7/28 | 0/8 |
| Exploratory boss | 1.2 | 7/28 | 7/28 | 0/8 |
| Exploratory boss | 2.4 | 15/28 | 15/28 | 0/8 |
| Confirmatory duel | 0.6 | 60/120 | 60/120 | 0/16 |
| Confirmatory duel | 1.2 | 69/120 | 69/120 | 0/16 |
| Confirmatory duel | 2.4 | 65/120 | 65/120 | 0/16 |
| Confirmatory gauntlet | 0.6 | 103/120 | 103/120 | 0/16 |
| Confirmatory gauntlet | 1.2 | 104/120 | 104/120 | 0/16 |
| Confirmatory gauntlet | 2.4 | 104/120 | 104/120 | 0/16 |
| Confirmatory boss | 0.6 | 63/120 | 60/120 | 1/16 |
| Confirmatory boss | 1.2 | 55/120 | 55/120 | 0/16 |
| Confirmatory boss | 2.4 | 64/120 | 64/120 | 0/16 |

The alternative reduced seed disagreement in some cells, increased it in
another and often selected the same action. Coefficients also changed choices.
This supports a diagnostic while retaining the existing engine/default rule and
coefficient. Stability alone does not justify stronger decisions or a new default.

Literal SHA-256 identities:

- Frozen protocol: `4ece55d12c4afac0762f13d49614e13a8f0b9684985255053bebe8910eb3df06`.
- [Exploratory receipt](stability/exploratory-receipt.json): `6c4fdb1d08de0d1d0e379a57a49c9d7055db7ecd19391d0e03a77469bd44f243`.
- [Confirmatory receipt](stability/confirmatory-receipt.json): `cf503f18c5cd01c148c28aab5b3088ceb3bcf9c023ccef5eb14c1048a215dbda`.

The companion includes those files and the six original inputs under
`docs/stability/`. Repeat each exploratory input (`exploratory-duel.json`,
`exploratory-gauntlet.json`, `exploratory-boss.json`) with:

```powershell
& $py "$companion\decide_episode.py" "$companion\docs\stability\exploratory-duel.json" --step 0 --stability --seeds 101 102 103 104 105 106 107 108 --horizon 4 > C:\records\fresh-exploratory-duel.json
```

Repeat each confirmatory input (`confirmatory-duel.json`,
`confirmatory-gauntlet.json`, `confirmatory-boss.json`) with:

```powershell
& $py "$companion\decide_episode.py" "$companion\docs\stability\confirmatory-duel.json" --step 0 --stability --seeds 1001 1002 1003 1004 1005 1006 1007 1008 1009 1010 1011 1012 1013 1014 1015 1016 --horizon 4 > C:\records\fresh-confirmatory-duel.json
```

Substitute the other input names and fresh outputs. The default grid supplies
all three coefficients. The delivered companion observes changed helper/entry
hashes and possibly a different runtime. These commands make fresh diagnostics
from retained states, not bit-identical source replay of the frozen baseline.
Historical episode replay keeps its stricter identity requirements. The baseline
does not establish late-round, prior, root-parallel, other-horizon or arbitrary
custom-content policy quality.
