# Design decisions

Each entry records a choice the code makes, why, what lost, and where to
read it. Everything here is backed by a comment, docstring, or test in the
tree; nothing is aspirational.

## 1. Open-loop tree: nodes hold actions, not states

**Why.** Accuracy rolls, pip regeneration, and enemy behaviour are all
stochastic, so one action sequence fans out into many states. A closed-loop
tree would need a chance node for every roll. Storing only the action
sequence and replaying it from the root under fresh randomness makes a
node's mean automatically an average over the outcome distribution, which
is what "win probability of this move" means.

**What lost.** Closed-loop MCTS with explicit chance nodes: exact, but the
tree explodes and every random event needs bookkeeping. The open-loop cost
is re-simulating from the root on every descent.

**Where.** `engine/mcts.py` module docstring and `Node`.

## 2. Actions minted in one realization may be stale in another

**Why.** Because the tree replays actions rather than states, an action
chosen when the hand had seven cards may be replayed in a realization where
the player died earlier or pip regen went differently. The simulator
degrades a stale or unaffordable action to a pass instead of crashing or
casting at a discount.

**What lost.** Re-validating and re-choosing inside the simulator, which
would have made a node's statistics describe a different action than its
label.

**Where.** `engine/simulator.py`, `advance_round`, the two comments at the
top of step 1.

## 3. Reward shaping: wins discounted by depth, losses worth more when late

**Why.** With a flat 1.0 for any win, "kill in 3 rounds" and "chip away for
6" score within search noise of each other and the engine looks indifferent
to finishing fights; 4.5% per round (capped at 27%) separates them. With a
flat 0.0 for any loss, healing at 5% win probability scores the same as
dying now; a late loss worth up to 0.15 makes the engine heal, shield and
play for time when behind, and the cap keeps any win above any loss.

**What lost.** Pure win/loss reward, which is cleaner to explain and plays
worse. Neither constant was swept; both came from watching bad play and
fixing it, and the README says so.

**Where.** `MCTS._terminal_reward` docstring; README "Why open-loop MCTS"
and "What these numbers do not prove".

## 4. Horizon states are scored by an HP heuristic that credits setup

**Why.** Rollouts stop after `horizon_rounds`. Scoring an unfinished fight
by raw HP would call "trap now, one-shot next round" zero progress and the
search would never recommend it. The heuristic discounts an enemy's HP by
the traps on it and by the player's blades, and weights enemies by the
damage they deal, so killing the hard hitter registers as relief.

**What lost.** A pure win/loss signal from rollouts to terminal, which in
a fight that can run 20+ rounds would make every rollout long and most of
them noise.

**Where.** `GameState.heuristic_value` docstring in `engine/state.py`.

## 5. Ranking by mean, with visit counts shown

**Why.** `search()` returns root actions sorted by estimated win rate, with
visits as the tie-break, because the caller wants a win-probability table
to display. The usual "robust child" rule (pick the most-visited action)
is not used, so a lightly visited action with a lucky mean can outrank a
well-explored one. The visit column exists so a reader can see when that
is happening.

**Where.** `MCTS.search` docstring; the demo prints both columns.

## 6. Root parallelism, not tree parallelism

**Why.** The search is pure Python, so threads on one tree would serialize
on the GIL, and sharing a tree across processes would mean locking or
shipping it. N independent searches with different seeds need no
synchronization; the parent sums per-action visits and value sums (raw
sufficient statistics, not rates, so the merge is exact) and re-derives
win rates. Independent trees also decorrelate exploration noise, so close
decisions flip less between polls.

**What lost.** Tree parallelism with virtual loss: more sample-efficient,
much more code, and pointless under the GIL. The cost of root parallelism
is that workers repeat each other's early exploration.

**Where.** `engine/parallel.py` module docstring, `merge_results`, and
`tests/test_parallel.py`, which checks that the merge is a sum and not an
average of rates.

## 7. Clone by hand; share what never mutates

**Why.** The search clones the state thousands of times per decision.
`copy.deepcopy` is far too slow and would copy things that are never
written: cards, resist tables, enemy policies, and the boss rules are
shared by reference; charm lists and DoTs are copied because the simulator
mutates them.

**What lost.** `deepcopy` (slow), or immutable state with structural
sharing (a rewrite of the simulator).

**Where.** `engine/state.py` module docstring and the comments inside
`Combatant.clone` and `GameState.clone`; `test_clone_is_deep_where_it_must_be`.

## 8. Boss mechanics as stateless rule objects

**Why.** Special encounter mechanics stay out of the damage model. A rule
is a function of (state, event); the simulator fires events at fixed points
in a round and each rule mutates the state to model its effect. Rules hold
no mutable data, so cloning a state shares them, and every simulated line
still pays the price of a mechanic — the search will not walk into a
punisher's counterattack because the counterattack happens inside the
rollouts.

**Where.** `engine/rules.py`; the README's demo shows the consequence
(a trap ranked below passing against a boss that punishes traps).

## 9. Annotations that a compiled build can use

**Why.** The parent project compiled `engine/` with mypyc. That is why
`Node` has every attribute annotated with no `__slots__` (native classes
are implicitly slotted), nullable fields are typed `Optional`, containers
carry concrete element types, and the frozen `Action` dataclass defines
`__reduce__` so parallel workers can pickle it back. `mypy` is clean on
`engine/` and CI keeps it that way.

**What lost.** Untyped containers and plain `dict`/`list` annotations,
which cost most of the compiled speedup.

**Where.** Comments in `engine/mcts.py` (`Node`), `engine/state.py`
(`Combatant`), `engine/actions.py` (`__reduce__`); README "Performance
notes".

## 10. Content is JSON, validated loudly at load time

**Why.** The engine never reads a file; it consumes plain `Card` and
`Combatant` objects. All example content lives in `data/*.json` and goes
through `game/loader.py`, which rejects unknown elements, malformed cards,
deck references to missing cards, out-of-range stats, and unknown or
mistyped boss-rule parameters with a message naming the offending entry.
A content error caught at load time is cheap; the same error surfacing as
odd behaviour thousands of simulations deep is not.

**Where.** `game/loader.py` docstring and `RULE_REGISTRY`; `tests/test_loader.py`.

## 11. Reproducibility: seed plus a pinned simulation count

**Why.** A seed alone does not reproduce a search, because a wall-clock
budget stops at a machine-dependent number of simulations. The tests pin
both, the demo's `--sims` does the same, and a loader test pins the exact
RNG stream so a content edit cannot silently shift every seeded result.

**Where.** `mcts_decider` docstring in `game/baselines.py`;
`test_determinism_under_fixed_seed`; `test_rng_stream_parity_with_precomputed_hand`;
`demo.py`.

## 12. Error bars come from code

**Why.** Sixty games per cell is a small sample. Every benchmark cell
carries a Wilson interval and every row a z-score for the search against
its best baseline, computed by `game/stats.py` and pinned by tests to the
numbers the README quotes. The benchmark's markdown output records the
interpreter, platform, and machine, so a table never travels without its
provenance.

**Where.** `game/stats.py`, `benchmark.py`, `tests/test_stats.py`,
`tests/test_benchmark.py`.

## Not done, on purpose or not yet

- No sensitivity sweep of the exploration constant (1.2) or the two
  reward-shaping constants.
- No robust-child selection, RAVE, progressive widening, or transposition
  table.
- No second game to test the "game-agnostic" claim beyond the one 9-card
  domain shipped here.
- The benchmark runs the single-process engine; the parallel engine is
  covered by tests but its speedup is not measured in this repo.
