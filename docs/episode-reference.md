# Price and inspect a saved one-round decision

Use the complete [episode companion](episode-companion.md) with its matching
installed engine. The `reference_episode.py` command consumes an existing
decision report, including a passively extracted stability cell. It does not
start another search or replay the encounter. This addition is separate from
the engine wheel and the saved episode reader kit.

The companion also provides an explicit [bounded two-round adaptive
reference](episode-adaptive-reference.md). Its separate report family prices
a supplied modeled state or an admitted saved horizon-two decision. Use that
guide for the small installed example, observation-dependent second choices
and transition/work-unit limits. The routes below retain their one-round meaning.

The [fixed search-allowance diagnostic](episode-search-allowance.md) uses this
existing one-round reference to compare the exact loss of decisions made with
8 or 64 simulations on declared saved states. Its bundled original pairs can
be inspected without calculation, and its complete result table keeps every
declared case and seed. The finding does not change the engine's defaults.

## Calculate, inspect and compare

First obtain a decision with `--horizon 1` using the existing saved-state command.
The reference reads its complete normalized pre-action state without refilling
the hand or resources. These examples assume the installation journey supplied
`$py` and `$companion`. Use fresh output names and check `$LASTEXITCODE` after
each command. PowerShell 7.4 or later preserves native stdout bytes. Older
Windows PowerShell redirection can change the encoding.

```powershell
& $py "$companion\decide_episode.py" C:\work\episode.json --step 0 --seed 19 --sims 16 --horizon 1 --final-action-rule mean_visits > C:\work\decision.json
& $py "$companion\reference_episode.py" C:\work\decision.json --max-seconds 10 > C:\work\reference.json
& $py "$companion\reference_episode.py" C:\work\reference.json --inspect --appearance obscur > C:\work\reference.html
& $py "$companion\reference_episode.py" C:\work\reference.json --inspect --compare-report C:\work\reference-other.json > C:\work\reference-comparison.html
```

Open the completed HTML locally. Inspection and comparison read saved values
without pricing, searching, drawing randomness or replaying transitions. The
pages show model and producer identities, exact fractions, action ties,
probability outcomes and comparison eligibility. Reading confirms internal
schema and arithmetic consistency. It does not recompute the transition model
or authenticate whoever supplied a file.

To use an existing horizon-one stability result, passively extract a constituent
with `decide_episode.py --extract-cell INDEX --final-action-rule mean_visits`,
then supply that decision JSON. Version 2 allows both final-action rules to be
assessed from the same retained root statistics, with no new simulations.
Version 1 preserves its recorded recommendation and does not infer missing
encounter order for alternate ties.

## Choose the admitted state model

The calculation model is an explicit choice. Omitting `--model` preserves the
original one/two-enemy route. It does not expand automatically when a saved
state contains three enemies.

| Calculation option | Report model identity | Admitted initial enemies |
| --- | --- | --- |
| Default, or `--model one-round` | `independent_one_round_binary53_shaped_v1` | One or two living enemies |
| `--model three-enemy` | `independent_one_round_three_enemy_binary53_shaped_v1` | Exactly three living enemies |

Both models use the same one-round objective, probability law and field bounds.
The Python consumer accepts the full model identity through its `model` keyword.
An unknown identity or command option is an input error. A valid saved state
outside the chosen subset produces a refusal with no accepted reference values.
Existing schema-version-1 reports retain their stored model and meaning.
Inspection reads that model from the saved report and rejects `--model` and
calculation controls. It cannot reinterpret an older result as a new model.

The bundled initial `gauntlet` state is a usable three-enemy example. Record
and replay a bounded episode, obtain a separate horizon-one decision, then
price its retained initial state with the explicit model:

```powershell
& $py "$companion\episode.py" record gauntlet --environment-seed 37 --search-seed 41 --rounds 1 --sims 16 --horizon 1 > C:\work\gauntlet-episode.json
& $py "$companion\episode.py" replay C:\work\gauntlet-episode.json > C:\work\gauntlet-replay.json
& $py "$companion\decide_episode.py" C:\work\gauntlet-episode.json --step 0 --seed 43 --sims 16 --horizon 1 > C:\work\gauntlet-decision.json
& $py "$companion\reference_episode.py" C:\work\gauntlet-decision.json --model three-enemy --max-seconds 10 > C:\work\gauntlet-reference.json
& $py "$companion\reference_episode.py" C:\work\gauntlet-reference.json --inspect --appearance obscur > C:\work\gauntlet-reference.html
& $py "$companion\reference_episode.py" C:\work\gauntlet-decision.json --model three-enemy --max-seconds 5 > C:\work\gauntlet-reference-other.json
& $py "$companion\reference_episode.py" C:\work\gauntlet-reference.json --inspect --compare-report C:\work\gauntlet-reference-other.json > C:\work\gauntlet-reference-comparison.html
```

These commands keep the same acquisition, encoding, fresh-path and exit-status
requirements as the first journey. Different cooperative limits are visible in
comparison and do not change the objective. Comparison requires matching exact
state, model identity, law and objective. Different model identities are
ineligible even when the remaining report fields agree.

## Choose an explicit computation method

The default `--method physical` retains the original transition enumeration,
physical leaf limits and schema-version-1 reports. Selecting
`--method sum-convolution` uses `integer_sum_convolution_v1` for a narrower
part of the same selected mathematical model. There is no automatic fallback
when physical enumeration reaches its limit.

For an admitted three-enemy saved decision:

```powershell
& $py "$companion\reference_episode.py" C:\work\decision.json --model three-enemy --method sum-convolution --max-contributions 1000000 --max-payoff-evaluations 10000 --max-seconds 10 > C:\work\reference-sum.json
& $py "$companion\reference_episode.py" C:\work\reference-sum.json --inspect --appearance obscur > C:\work\reference-sum.html
& $py "$companion\reference_episode.py" C:\work\reference-physical.json --inspect --compare-report C:\work\reference-sum.json > C:\work\reference-method-comparison.html
```

This method admits nonlethal plain damage with no affordable enemy response,
charms, damage over time, healing, resistance or boost. Explicit zero-valued
resistance and boost entries are allowed. Every enemy must have a source threat
factor of exactly one, with no base attack supplied and too few effective
resources for the default response. Every hand card must deal plain damage,
with zero heal, damage-over-time and modifier fields, including unaffordable
cards. Every offered card's largest roll must leave every possible target
alive. These are deliberate method limits. They do not establish that every
excluded state is mathematically impossible to aggregate. The original model's
normalized field, enemy, card-width and action bounds still apply.

Current and maximum HP may differ among enemies, and the player may be injured.
Damage ranges, positive accuracy, costs, names, elements and final resource
regeneration may vary within those bounds. Duplicate cards and single-target
choices keep their physical indices. Accuracy is one shared cast event for all
targets, followed by independent damage rolls on success. The method groups
damage rolls by their integer sum, evaluates the original binary64 payoff at
each total, and sums out
final regeneration for values and outcome masses. It does not produce a
successor-state distribution or a draw tape for later decisions.

Schema-version-2 reports retain `computation_method`, distinct limits and `work`
counters. `contributions` counts executed integer multiplicity additions and
`payoff_evaluations` counts executed binary64 payoff calculations, including
pass and any positive accuracy-miss branch. `peak_bins` is the largest individual
damage-sum distribution stored for any action. It does not count all temporary
distributions simultaneously or measure peak memory. Represented physical
damage tuples and positive trace leaves describe branches covered
mathematically, including omitted regeneration. They were not enumerated.
These counters do not establish
a measured speedup or memory guarantee.

Defaults cap whole-report work at 1,000,000 contribution updates and 10,000
payoff evaluations, with a finite positive cooperative deadline of at most
30 seconds. The two work flags may lower their caps. Physical leaf controls
cannot limit sum-convolution work and the command rejects mixed controls.
The Python consumer selects the full method identity through `method` and
accepts the corresponding `max_contributions` and `max_payoff_evaluations`
keywords. An unsupported action or exhausted work refuses the entire report.

Inspection reads the stored method, rejects calculation controls and does no
numerical work. Historical schema-version-1 reports retain their hashes,
diagnostics and physical leaf meaning. Cross-method comparison is eligible
when complete exact states, model, law, objective and values agree. Different
work units and policies are shown without treating them as a model mismatch.

## Objective and evidence boundary

Each one-round model in this guide prices every legal physical action after one complete round.
Terminal depth and horizon are both one.
A win uses the source binary64 value `1.0 - 0.045`, a loss uses `0.15`, including
simultaneous death, and an ongoing state uses the original HP/setup score in
its source floating operation order. A nearly finished ongoing state can score
above a terminal win. The model preserves that objective.

The probability law uses independent uniform values `k / 2**53` for `random`
draws and independent uniform inclusive integer damage draws. Accuracy retains
the inclusive source threshold. Enemy attempt and regeneration retain their
strict thresholds. Values are exact rational expectations of those binary64
payoffs. Numerators and denominators are decimal strings so large fractions
survive JSON and browser readers. Display floats never determine ties or loss.

Loss is the largest reference expectation minus the selected action's
expectation. Zero means the action belongs to the exact best-action tie set
under this objective. It does not establish full-encounter optimality,
calibrated win probability, stronger playing performance or exact averaging
over Python's finite random-generator states. Search means remain sampled
shaped scores. The existing sampled one-round comparator uses a different
win/loss objective.

The report binds the qualified nine engine body hashes, observed installation,
saved decision producer, reference producer and exact state representation.
An unqualified installed engine is refused. The
[complete qualified source maps](https://github.com/T92T1914/mcts-combat-engine/blob/3888e6fc0d17a990f03b0eb6e2c81d00a5cd59ca/reference/report.py) preserve the original
engine declarations and later separately qualified implementations. The
[compatibility guide](model-compatibility.md) explains the threshold and reward
documentation changes without rewriting historical identities. A complete report
binds its observed engine to its own declared qualified map. Historical reports
keep that original declaration.
A decision from different engine code can have its supported state priced,
but its quality comparison is ineligible.
Original source-byte hashes remain retained claims. Hashes identify bytes, not
trusted authorship. Historical episode admission and replay remain unchanged.

## Supported subset and limits

The chosen subset requires one/two or exactly three living initial enemies as
listed above, a living player, no boss flags/rules or learned policy, and at most
one initially affordable enemy response. It
admits up to seven hand cards and seven resource slots, all current card types,
supported damage/heal/setup/status effects and explicit normalized fields.
Duplicate cards and targets retain distinct physical indices. A full seven-card
hand of single-target attacks has up to 15 physical choices in the default model
and 22 in the three-enemy model, including pass. Damage ranges
span at most 151 integer values. HP and damage are bounded at one million,
root charm and damage-over-time lists have at most four entries, and positive
effect lifetimes are bounded at 30 rounds. The implementation states complete
field bounds and refuses any whole state outside them. No rule, target,
status or probability branch is discarded to fit.

Defaults are 250,000 leaves per action, 1,000,000 per report and a 30 second
cooperative calculation deadline. `--max-paths`, `--max-total-paths` and
`--max-seconds` can lower them. Time checks occur during enumeration and at
calculation completion. These controls do not bound process startup, identity
capture, report validation, output time or memory. They are not a hard wall or
memory cap. An admitted state can still exceed a work limit. A caller needing
stronger isolation must own external process limits.

All actions must complete before any reference value is accepted. Unsupported
state, engine or horizon, exhausted work, interruption and calculation failure
produce a refused report with no evaluation or score-loss result. Malformed
input or invalid controls exit 2 before a report. Complete calculation and
passive inspection exit 0. Refusal or runtime/output failure exits 1.
Interruption exits 130. Interruption before input capture or a failed output
sink can prevent JSON delivery.

Output is flushed complete JSON or HTML with LF. Shell redirection can create
or overwrite a target before failure. It is not atomic or durable storage.
Retain stderr, exit status and original files alongside a saved result.
