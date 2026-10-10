# Price and inspect a saved one-round decision

Use the complete [episode companion](episode-companion.md) with its matching
installed engine. The new `reference_episode.py` command consumes an existing
decision report, including a passively extracted stability cell. It does not
start another search or replay the encounter. This addition is separate from
the engine wheel and the saved episode reader kit.

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

## Objective and evidence boundary

Model `independent_one_round_binary53_shaped_v1` prices every legal physical
action after one complete round. Terminal depth and horizon are both one.
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
A different installed engine is refused. A decision from different engine code
can have its supported state priced, but its quality comparison is ineligible.
Original source-byte hashes remain retained claims. Hashes identify bytes, not
trusted authorship. Historical episode admission and replay remain unchanged.

## Supported subset and limits

The subset has one or two living enemies, a living player, no boss flags/rules
or learned policy, and at most one initially affordable enemy response. It
admits up to seven hand cards and seven resource slots, all current card types,
supported damage/heal/setup/status effects and explicit normalized fields.
Duplicate cards and targets retain distinct physical indices. Damage ranges
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
