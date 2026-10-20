# Design decisions

Each entry records a choice the code makes, its tradeoff and where to inspect
the implementation. The linked studies keep measured results separate from
the reasons for a design choice.

## 1. Open loop tree: nodes hold actions, not states

**Why.** Accuracy rolls, pip regeneration, and enemy behaviour are all
stochastic, so one action sequence fans out into many states. A closed loop
tree would need a chance node for every roll. Storing only the action
sequence and replaying it from the root under fresh randomness makes a
node's mean automatically an average over the outcome distribution, with shaped rewards rather than calibrated win probabilities.

**Tradeoff.** An explicit chance tree can represent distinct outcomes, but adds
state and branch bookkeeping. That representation alone does not make a finite
search exact. The open loop design instead simulates from the root on every
descent.

**Where.** `engine/mcts.py` module docstring and `Node`.

## 2. Stable action identity and state dependent availability

**Why.** Removing a card changes later list indexes. Reusing that index in another stochastic realization could select a different card, even when the resulting move was legal. Tree edges now identify the original root hand slot; a per simulation slot map resolves the current index. Duplicate card copies remain distinct.

Legal moves are recomputed for each realized state. Newly available edges can expand; currently unavailable edges cannot be selected and do not receive credit for a substituted pass. The simulator separately validates external inputs as defense in depth.

**Cost.** Each visited node recomputes availability and maps actions. Values are conditional on the realizations where an edge is available. This does not implement a full chance tree or an availability aware UCB variant.

**Where.** `engine/mcts.py`, `_available_actions` and `MCTS.search`; `engine/actions.py`, `is_legal_action`; `tests/test_action_identity.py`.

## 3. Reward shaping: wins discounted by depth, losses worth more when late

**Why.** A terminal win loses 4.5% per simulated depth step, capped at 27%.
A terminal loss receives a survival component that rises to 0.15 at the
horizon. At depth one, its value is `0.15 / max(1, horizon_rounds)`, rather
than necessarily zero. These bounds keep individual terminal wins above
terminal losses. Ongoing horizon states use the separate HP/setup heuristic
in `[0, 1]`, which can score above a win or below a loss.

**Tradeoff.** Shaping supplies a signal before full encounters finish, but
changes the objective from terminal wins alone. Neither constant received a
parameter sweep. The formulas do not guarantee healing, stronger action
rankings or avoidance of stalling, and no controlled comparison here establishes
that this reward plays better than a pure win/loss reward.

**Where.** `MCTS._terminal_reward` in `engine/mcts.py`, the
[reward compatibility explanation](model-compatibility.md#reward-explanation-and-raw-source-identity)
and the README's [evidence limits](../README.md#what-these-numbers-do-not-prove).

## 4. Horizon states are scored by an HP heuristic that credits setup

**Why.** Rollouts stop after `horizon_rounds`. A score based only on current
HP would omit setup that has not dealt damage yet. The heuristic discounts an enemy's HP by
the traps on it and by the player's blades, and weights enemies by the
damage they deal, so killing the hard hitter registers as relief.

**Tradeoff.** Stopping at a horizon avoids requiring every rollout to reach
a terminal state, but makes the chosen heuristic part of the search objective.
It does not establish the best full encounter action.

**Where.** `GameState.heuristic_value` docstring in `engine/state.py`.

## 5. Ranking by mean, with visit counts shown

**Why.** `search()` returns root actions sorted by mean shaped reward, with
visits as the tie break. The compatibility field is named `win_rate`, but
its value includes terminal shaping and a horizon heuristic. The usual "robust child" rule (pick the most visited action)
is not used, so a lightly visited action with a lucky mean can outrank a
well explored one. The visit column exists so a reader can see when that
is happening.

**Where.** `MCTS.search` docstring; the demo prints both columns.

## 6. Root parallelism, not tree parallelism

**Why.** In the supported Python execution path, CPU threads contend on the
GIL. Separate processes build independent trees without synchronizing tree
updates. The parent sums per action visits and raw value sums, then derives
the weighted means instead of averaging worker means equally. Changing worker
count changes the forest and can change the selected action.

**Tradeoff.** Workers repeat early exploration. A shared tree would need
coordination and a different implementation. The retained process studies
measure this independent-root design, not the sample efficiency of an
unimplemented shared tree or a guarantee of more stable choices.

**Where.** `engine/parallel.py` module docstring, `merge_results`, and
`tests/test_parallel.py`, which checks that the merge is a sum and not an
average of rates.

## 7. Clone by hand, share what never mutates

**Why.** The search clones the state thousands of times per decision.
Copying only the changing state avoids a generic recursive copy. Cards,
resist tables, enemy policies and boss rules are shared by reference under a
read only definition convention. Charm lists and DoTs are copied because the
simulator mutates them. The caller must keep those shared definitions stable,
as explained in the [managed input contract](managed-decider.md#keep-caller-inputs-stable).

**Tradeoff.** A generic `deepcopy` or immutable state with structural sharing
would be a different implementation. No separate timing comparison between
those alternatives is claimed here.

**Where.** `engine/state.py` module docstring and the comments inside
`Combatant.clone` and `GameState.clone`; `test_clone_is_deep_where_it_must_be`.

## 8. Boss mechanics as stateless rule objects

**Why.** Special encounter mechanics stay out of the damage model. A rule
is a function of (state, event); the simulator fires events at fixed points
in a round and each rule mutates the state to model its effect. Rules hold
no evolving encounter data, so cloning a state shares their configuration.
Their effects occur inside each simulated line. The search can therefore
sample a counterattack when evaluating an action. This does not guarantee
that its selected action avoids the penalty.

**Where.** `engine/rules.py`; the README's demo shows the consequence
(a trap ranked below passing against a boss that punishes traps).

## 9. Annotations that a compiled build can use

**Why.** The source retains annotations intended for an optional mypyc build.
`Node` has every attribute annotated with no `__slots__` (native classes
are implicitly slotted), nullable fields are typed `Optional`, containers
carry concrete element types, and the frozen `Action` dataclass defines
`__reduce__` so parallel workers can pickle it back. `mypy` is clean on
`engine/` and CI keeps it that way.

**Limit.** These source choices do not establish a delivered compiled package
or a measured compilation speedup. The public performance studies identify
their actual Python execution paths separately.

**Where.** Comments in `engine/mcts.py` (`Node`), `engine/state.py`
(`Combatant`), `engine/actions.py` (`__reduce__`) and the README's
[evidence limits](../README.md#what-these-numbers-do-not-prove).

## 10. Content is JSON, validated loudly at load time

**Why.** The engine never reads a file; it consumes plain `Card` and
`Combatant` objects. All example content lives in `data/*.json` and goes
through `game/loader.py`, which rejects unknown elements, malformed cards,
deck references to missing cards, out of range stats, and unknown or
mistyped boss rule parameters with a message naming the offending entry.
A content error caught at load time is cheap; the same error surfacing as
odd behaviour thousands of simulations deep is not.

**Where.** `game/loader.py` docstring and `RULE_REGISTRY`; `tests/test_loader.py`.

## 11. Reproducibility: seed plus a pinned simulation count

**Why.** A seed alone does not reproduce a search, because a wall clock
budget stops at a machine dependent number of simulations. The tests pin
both, the demo's `--sims` does the same, and a loader test pins the exact
RNG stream so a content edit cannot silently shift every seeded result.

**Where.** `mcts_decider` docstring in `game/baselines.py`;
`test_determinism_under_fixed_seed`; `test_rng_stream_parity_with_precomputed_hand`;
`demo.py`.

The full-game runner gives policy choices a separate random stream from deck
draws and environment outcomes. A policy that draws randomness and then ignores
it must not change the encounter. The benchmark resets search at each scenario
boundary so selecting or reordering scenarios does not shift another scenario's
search stream. Within one scenario, search state continues across its games.
Game and policy seeds are recorded independently. Decision simulation counts
also show whether a safety time limit interrupted a requested fixed budget.
See `tests/test_experiment_rng.py` for the coupled-stream and scenario-order
regressions. This separation does not force different actions to experience
identical later random events.

## 12. Error bars come from code

**Why.** Sixty games per cell is a small sample. Every benchmark cell
carries a Wilson interval and every row a z score for the search against
its best baseline, computed by `game/stats.py` and pinned by tests to the
hand checked numbers of the first benchmark run (the committed table is a
later run of the same code). The benchmark's markdown output records the
interpreter, platform, and machine, so a table never travels without its
provenance.

**Where.** `game/stats.py`, `benchmark.py`, `tests/test_stats.py`,
`tests/test_benchmark.py`.

## 13. Policy healing uses elemental resource value

An enemy policy's heal costs two pips in the enemy's own element. One power
pip pays that cost, just as it does for a matching card. The affordability
check uses the same resource value as payment. Previously, the policy
counted that power pip as one and skipped an affordable heal.

The regression uses a hand checked payment table and a one-round HP oracle.
It also checks the heal cap, integer rounding, random draws and a one-simulation
search result. The shipped scenarios do not set enemy policies, so this
correction does not revise their retained study results.

**Where.** `engine/simulator.py`, `enemy_act`; `tests/test_enemy_policy_heal.py`.

## Not done, on purpose or not yet

* No sensitivity sweep of the two reward shaping constants. The retained
  [stability diagnostic](episode-stability.md#retained-baseline) compares
  exploration coefficients 0.6/1.2/2.4 over six early states, with 216 completed
  calls. That scoped result retains the mean-first engine rule and the
  hand-chosen default 1.2. It does not establish stronger decisions or optimality.
* No robust child final selection in the engine. The companion compares
  visits-first and mean-first choices from the same captured statistics in
  that diagnostic. No RAVE, progressive widening, or transposition table.
* No second game to test the "game agnostic" claim beyond the one 9 card
  domain shipped here.
* The historical encounter benchmark uses the single process engine. Separate
  [process scaling](parallel-scaling-results.md), [same forest](same-forest-results.md)
  and [repeated execution](same-forest-repeatability-results.md) studies now
  retain bounded timing comparisons. They do not establish full encounter
  throughput, playing strength or general hardware scaling.
