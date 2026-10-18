# Inspect an exact two-round adaptive reference

For a fixed-work comparison using this target to price both horizon-one and
horizon-two first choices, see the [two-round horizon study](two-round-horizon.md).
Its declared result is inconclusive and the existing saved-decision admission
below is unchanged.

The complete [episode companion](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-companion.md) can price a small
normalized state over exactly two rounds. After each complete first-round
observation, the calculation chooses the legal second action with the highest
exact conditional expectation. The first action stays fixed while its second
choice can depend on the observed state. Every offered first action and every
legal continuation must complete before a reference result is accepted.

Select both `--model two-round-adaptive` and `--method adaptive-physical`.
This explicit route emits `mcts-two-round-adaptive-reference-report`, version 1,
with model `independent_two_round_adaptive_binary53_shaped_v1`. The existing
one-round report versions, methods and default calculation retain their meaning.

## Run the supplied modeled state with an installed engine

Obtain the companion ZIP and matching engine separately through the
[installation guide](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-companion.md#acquire-both-parts). Extract the whole
companion and install the engine with ordinary pip or a separately acquired
matching wheel. The wheel installs only `engine/`. The companion carries the
reference and example source, with no engine copy or wheel. A development
checkout, Git and development extras are unnecessary for this journey.

The included `examples/adaptive-state.json` is an explicitly supplied modeled
state. It has one living enemy, two zero-cost plain damage cards and an explicit
width-one enemy response. It is neither a captured encounter nor a recorded
episode. The default scenario loader creates seven cards and the encounter
runner refills that hand before each recorded decision, so those ordinary
recordings do not provide this smaller root.

These PowerShell examples assume the installation guide supplied `$py` and
`$companion`, and that `C:\work` already exists. Use fresh output names, retain
stderr and check `$LASTEXITCODE` after each command. PowerShell 7.4 or later
preserves native stdout bytes. Older Windows PowerShell can change the encoding.

```powershell
& $py "$companion\reference_episode.py" "$companion\examples\adaptive-state.json" --state-input --model two-round-adaptive --method adaptive-physical --max-transitions 1000 --max-per-action 500 --max-work-units 3000 --max-seconds 10 > C:\work\adaptive-reference.json
& $py "$companion\reference_episode.py" "$companion\examples\adaptive-state.json" --state-input --model two-round-adaptive --method adaptive-physical --max-seconds 5 > C:\work\adaptive-reference-other.json
& $py "$companion\reference_episode.py" C:\work\adaptive-reference.json --inspect --appearance obscur > C:\work\adaptive-reference.html
& $py "$companion\reference_episode.py" C:\work\adaptive-reference.json --inspect --compare-report C:\work\adaptive-reference-other.json --appearance obscur > C:\work\adaptive-comparison.html
```

The first two commands calculate exact expectations under the declared model.
They do no search, episode replay or sampled transition work. The last two read
saved report values and produce passive HTML. Open the completed files locally.
Inspection and comparison perform no calculation, search, random draw or
replay. The pages preserve exact fractions and the complete saved observation
and continuation maps. Reading checks internal schema and arithmetic consistency
without recomputing the transition model or authenticating the producer.

The direct state report retains source byte identity, exact selected state,
qualified engine body hashes and observed producer identities. Its
`decision_report`, selected-action loss and sampled-statistics comparison are
absent because the input supplies no saved search recommendation. Two complete
direct reports with matching state, model, law and objective can be compared.
Different work controls remain visible without changing that objective.

## Search the same state through the public Python API

To sample a recommendation on that same two-card root, save the following as
`adaptive_search.py` outside the companion and run `& $py C:\work\adaptive_search.py`.
It needs only the installed engine and Python's standard library. It constructs
the supplied model directly rather than editing an episode or refilling a hand.

<!-- adaptive-api-recipe:start -->
```python
import copy
import json
import random

from engine import Card, CardType, Combatant, Element, GameState, MCTS

state = GameState(
    player=Combatant(
        "Modeled operator", Element.EMBER, hp=100, max_hp=100,
        power_pip_chance=0,
    ),
    enemies=[Combatant(
        "Modeled target", Element.EMBER, hp=3, max_hp=100,
        power_pip_chance=0,
        base_attack=Card(
            "Plain response", Element.NEUTRAL, CardType.DAMAGE,
            pip_cost=7, accuracy=1, damage_min=1, damage_max=1, modifier=0,
        ),
    )],
    hand=[
        Card("Variable hit", Element.EMBER, CardType.DAMAGE,
             accuracy=1, damage_min=1, damage_max=2, modifier=0),
        Card("Fixed hit", Element.EMBER, CardType.DAMAGE,
             accuracy=1, damage_min=1, damage_max=1, modifier=0),
    ],
)
before = copy.deepcopy(state)
search = MCTS(
    horizon_rounds=2, max_sims=16, max_transitions=32,
    rng=random.Random(19),
)
ranked = search.search(state, time_budget_ms=None)
if state != before:
    raise RuntimeError("Search changed its input state")
selected = ranked[0] if ranked else None
print(json.dumps({
    "selected_action": None if selected is None else {
        "card_idx": selected.action.card_idx,
        "target_idx": selected.action.target_idx,
    },
    "mean_shaped_reward": None if selected is None else selected.win_rate,
    "visits": None if selected is None else selected.visits,
    "simulations": search.last_sims,
    "transitions": search.last_transitions,
    "unused_transitions": search.last_unused_transitions,
    "stop_reasons": search.last_stop_reasons,
}, indent=2))
```
<!-- adaptive-api-recipe:end -->

The search uses ordinary UCT, no priors and the existing mean-then-visits ranking.
The seed fixes this example's random stream. The limits permit at most 16
simulations and 32 simulated rounds, including traversal and rollout. A terminal
branch can use fewer rounds. Disabling the clock makes work reproducible, but
does not impose a hard time or memory limit. The output reports actual work.

`card_idx` is the original zero-based hand position here and `target_idx` is
the enemy position. A Pass has both coordinates null. The recommendation does
not execute that action. With no simulations and no priors, the ranking is empty
and this code emits null recommendation fields. `win_rate` is the API's historical
field name for mean shaped reward, not a calibrated win probability.

The exact table below prices the same root under its declared adaptive
objective. A sampled recommendation need not select that optimum. The printed
JSON is an informal example output, not a saved decision report accepted by
`reference_episode.py`. Use the supported saved-decision route below when a
joined decision/reference report is required. This recipe neither changes that
admission contract nor adds evidence to the completed horizon study.

## What adapts in the example

The variable hit deals one or two damage into enemy HP three. After that first
action, the remaining fixed hit is still original physical card 1, now at current
hand index 0. Enemy HP two and enemy HP one are separate observations with exact
probability one half each. Both Pass and the fixed hit remain legal in both.
The optimal continuation is the fixed hit at HP two and Pass at HP one.

| Ordered first action | Exact adaptive expectation |
| --- | --- |
| Pass | `17879290520660869 / 18014398509481984` |
| Variable hit, original card 0 | `8962163258467287 / 9007199254740992` |
| Fixed hit, original card 1 | `4458563631096791 / 4503599627370496` |

The variable hit is the unique best first choice for this model. The behavior
comes from the preserved shaped objective: an ongoing state near completion can
score above a terminal win. Passing at HP one is therefore a meaningful
observation-dependent choice, even though it may look unusual as encounter
strategy. These values establish the modeled calculation on this state. They
do not establish improved playing performance.

Each root row includes complete first observations, ordered remaining cards,
their original root indices, every legal second action, exact conditional
values, tied best-action indices and the chosen first member of each exact tie.
Equal complete observations with equal physical-copy mapping may be grouped.
Grouping excludes random draw tapes and retains scalar types, resources, HP,
round, elements, base attacks and all other normalized state fields.

## Use an already supported saved decision

A saved decision can also be priced when its complete retained root belongs to
the subset below and its search horizon is exactly two. Obtain a fresh fixed-work
decision from an existing admitted episode state with the existing command:

```powershell
& $py "$companion\decide_episode.py" C:\work\supported-episode.json --step 0 --seed 19 --sims 16 --horizon 2 --final-action-rule mean_visits > C:\work\adaptive-decision.json
& $py "$companion\reference_episode.py" C:\work\adaptive-decision.json --model two-round-adaptive --method adaptive-physical --max-seconds 10 > C:\work\adaptive-decision-reference.json
```

This route consumes the actual saved pre-action state without refilling its hand
or resources. A compatible horizon-two stability cell can instead be passively
extracted through `decide_episode.py --extract-cell`. Calculation binds the saved
decision and reports exact loss for its selected action and the alternate rule
derived from the same retained statistics. That loss is the best modeled root
expectation minus the selected root expectation. Zero means membership in the
exact best-action tie set for this objective. A search from different engine
code or a different value declaration can have its state priced while its
quality comparison remains ineligible.

The direct state example is the installed entry point for the small subset.
Do not edit a recorded episode to imply that its content, identity or RNG
checkpoints were observed. Structurally admitted modeled test inputs remain
modeled inputs, and structural admission does not prove environment replay.

## Objective, probability and supported roots

The model horizon is two simulated rounds from the supplied root, independent of
the absolute round number. A depth-one or depth-two win uses the original
binary64 operation `1.0 - 0.045 * min(6, depth)`. A loss uses
`0.15 * (min(depth, 2) / 2)`, with player death taking priority, including
simultaneous death. An ongoing state at depth two uses the original ordered
HP/setup heuristic and explicit enemy attack threat factor. Terminal first
observations stop after that complete round. They are never advanced again.

The probability law is `iid_binary53_inclusive_integer_v1`. Each modeled random
draw is independent uniform `k / 2**53`, with integer `k` from zero through
`2**53 - 1`. Damage is independently uniform over its inclusive integer range.
Cast success preserves `random <= accuracy`. Enemy attempts and resource
regeneration preserve strict thresholds. Each source-order binary64 payoff is
converted to an exact fraction before probability weighting. This is neither
ideal decimal arithmetic nor averaging over Python's finite generator states.

An admitted root has a living player, exactly one living enemy and root round
1 through 30. It retains at most three hand cards. Each card is plain damage
with an inclusive range width at most three, or pure positive healing with zero
damage and `hits_all` false. The enemy's explicit base attack must be plain
damage with width at most three. An omitted default attack is unsupported.
Damage payloads have zero healing, damage-over-time and modifier fields. The
player's dormant base attack may be null or an admitted plain damage card.

No boss flag/rules, learned policy, initial charms or damage-over-time are
admitted. Resistance and boost maps may be empty or contain literal zeros.
Original normalized names, elements, HP, resources, chances and field bounds
apply. Initial accuracy must be positive. Unaffordable cards, duplicate physical
cards, empty hands, clipping and lethal outcomes remain explicit. The calculation
does not discard an excluded effect or probability branch to fit the subset.

Values are exact rational expectations of this adaptive shaped objective.
They are not calibrated win probabilities, full-encounter optimality or proof
of a stronger default policy. The existing search samples action paths and
retains its existing reward, selector and exploration coefficient. The new
reference does not change those defaults.

## Work limits, refusal and saved-report compatibility

Defaults cap executed transition leaves at 1,000,000 per report and 250,000 per
root action, with a combined cap of 3,000,000 work units. A root action's
transition count includes its first-round leaves and all offered second-action
leaves. Work units count executed transition leaves, binary64 payoff
evaluations and observation-group operations. The report separates first and
second transitions, payoff/group counts and request-local cache hits/misses.
They are different units from one-round physical leaves, sum-convolution
contributions and sampled search transitions.

`--max-transitions`, `--max-per-action` and `--max-work-units` may lower their
positive integer caps. Booleans and values above the ceilings are invalid.
`--max-seconds` must be finite, positive and at most 30. Time checks are
cooperative during admission, calculation and completion. They do not bound
process startup, identity capture, report validation or output, and provide no
hard elapsed-time or memory guarantee. Cache reuse is confined to one request.
A caller needing stronger containment owns external process limits.

An unsupported state, engine/horizon mismatch, exhausted work or calculation
failure refuses the whole report. A refused report has no accepted evaluation,
ranking or loss diagnostics. For example, adding `--max-transitions 1` to the
direct calculation deliberately produces a work refusal. The saved refusal can
still be passively inspected. Mixed one-round controls are input errors, and
inspection rejects calculation controls rather than reinterpreting saved data.

Complete calculation and passive inspection exit 0. Refusal or runtime/output
failure exits 1, invalid input/controls exit 2 and interruption exits 130.
An interrupted input capture or failed output sink can prevent JSON delivery.
Output is complete flushed JSON or HTML ending with LF. Shell redirection may
create or overwrite a file before failure and is neither atomic nor durable.

Historical one-round report versions remain inspectable with their original
hashes, diagnostics and work meanings. Comparing the new family with either
one-round version is explicitly ineligible for a common quality ranking.
Different model identities, exact states, laws or objectives are also
ineligible. Saved-report admission preserves producer claims without treating
hashes as trusted authorship or recalculating the model.
