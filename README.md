# mcts-combat-engine

[![CI](https://github.com/T92T1914/mcts-combat-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/T92T1914/mcts-combat-engine/actions/workflows/ci.yml)

A Monte Carlo Tree Search engine for stochastic, imperfect-information,
turn-based combat — pure Python, zero dependencies, with a toy card-duel
game to prove it plays well.

Extracted and generalized from a larger private project — a decision-support
engine for a complex turn-based strategy game, where this search core
(compiled with mypyc and fanned out across cores) evaluated 400,000+
simulations per decision inside a one-second budget. This repo is the
algorithmic core of that system with an original, self-contained example
game, so every claim here is runnable and testable on any machine with
Python 3.11+.

## Why open-loop MCTS

Classic MCTS stores a game state in every tree node. That breaks down when
the game is stochastic: accuracy rolls, resource regeneration, and enemy
behavior mean one action sequence leads to many possible states, and
state-per-node search needs explicit chance nodes for every die roll.

The open-loop variant stores only **action sequences** in the tree. Every
simulation replays its path from the root under fresh randomness, so a
node's value automatically averages over the whole outcome distribution —
which is exactly what "win probability of this move" means. The trade-off
(re-simulating from the root every time) is paid back by much smaller trees
and no chance-node bookkeeping.

Two reward-shaping details in `engine/mcts.py` came directly from watching
the engine play badly, and are the difference between "correct" and "plays
like a human":

- **Wins are discounted by depth** (4.5%/round). Without it, "kill in 3
  rounds" and "chip away for 6" score within noise of each other and the
  engine looks indifferent to finishing fights.
- **Losses are worth more the later they come** (up to 0.15). With a flat
  0.0 for every loss, healing at 5% win probability scores the same as
  dying immediately — the engine was blind to survival. This term makes it
  heal, shield, and play for time when behind, without ever preferring a
  slow loss to any win.

## What's in the box

```
engine/            the search engine (game-agnostic)
  state.py         combatants, cards, charms, DoTs; fast manual clone()
  actions.py       legal-move enumeration
  simulator.py     one stochastic round: cast -> enemy policies -> upkeep
  rules.py         pluggable boss mechanics ("punish traps", "enrage")
  mcts.py          open-loop UCB1 search with priors support
  parallel.py      root-parallel search: N processes, merged statistics
game/              the example game (content, not engine)
  loader.py        JSON -> validated Card/Combatant/rule objects
  content.py       loads data/ at import; exposes CARDS and SCENARIOS
  baselines.py     random and greedy policies to beat
  runner.py        seed-paired match harness
data/
  cards.json       the 9-card elemental deck
  scenarios.json   three encounters, incl. the boss and its rules
demo.py            watch one decision with ranked moves
benchmark.py       the table below
tests/             30 tests: mechanics, search sanity, loader validation,
                   beats-the-baselines
```

## Data-driven content

The engine never reads a data file — it consumes plain `Card`/`Combatant`
objects. All example content lives in `data/*.json`, parsed by
`game/loader.py`, which validates loudly at load time: unknown elements,
malformed cards, deck references to missing cards, out-of-range stats, and
unknown boss-rule types all fail with a message naming the offending entry.
Boss mechanics are data too — a registry maps rule names in
`scenarios.json` to `BossRule` classes, so `{"type": "punish_traps",
"damage": 350}` builds the same object code would. Adding a card or an
encounter means editing JSON; adding a new *mechanic* means one `BossRule`
subclass plus a registry entry. This mirrors the parent project's
architecture, where a knowledge base of thousands of cards and encounters
fed the same generic engine.

A parity test pins the shipped JSON to the exact RNG stream the benchmark
was measured with, so content edits can't silently invalidate the numbers
below.

## Results

Sixty games per policy per scenario, identical game seeds for every policy
(differences are policy, not luck). `greedy` always throws the biggest
affordable hit at the best target — the strongest "obvious" strategy.

| scenario | random | greedy | mcts (120 ms) |
|---|---|---|---|
| duel (1v1) | 90% · 20.2r | 35% · 16.2r | **100% · 17.9r** |
| gauntlet (1v3) | 55% · 23.4r | 32% · 17.2r | **95% · 17.9r** |
| boss (enrage + trap punish) | 20% · 25.9r | 3% · 17.0r | **55% · 23.4r** |

*win % = clean wins · Nr = average rounds to win, when it won*

Two things worth noticing:

- **Greedy loses to random on the duel.** Random occasionally heals and
  shields by accident; greedy never does. In a game where survival funds
  future damage, never healing is worse than playing randomly — the
  clearest possible demonstration that "deal max damage now" is a trap.
- **The boss is tuned to be genuinely hard** (enrages below half HP,
  punishes traps). Search wins 55% where the best naive policy manages
  20% — it learns to blade before it hits, race the enrage timer, and
  spend pips on heals only when the math demands it. Greedy's 3% is what
  "hit hardest every turn" is actually worth against a boss with a clock.

## What these numbers do not prove

- **Sixty games per cell is not many.** The 95% Wilson intervals are wide: the
  boss row's 55% is 42.5-66.9%, random's 20% is 11.8-31.8%. The gap between them
  is still decisive (two-proportion z = 3.96), and so is greedy's collapse. But
  the duel row, where search wins 100% against random's 90%, is z = 2.51 - real,
  and thinner than a bolded 100% suggests. Seed-pairing removes luck *between*
  policies, not the sampling error in each.
- **One game does not establish generality.** `engine/` never imports `game/`, and
  the split is real, but "game-agnostic" is an architectural claim demonstrated on
  a single 9-card domain. A second, structurally different game would test it; this
  repo has not run that test.
- **Greedy is the strongest baseline here, and it is not strong.** It never heals,
  which the duel row shows is a fatal flaw. Beating it is necessary, not
  sufficient - a hand-tuned heuristic that knew when to shield would be the honest
  next opponent.
- **The two reward-shaping constants were tuned by watching, not swept.** The 4.5%
  per-round win discount and the 0.15 late-loss term came from observing bad play
  and fixing it, which is how they are described above. Neither has a sensitivity
  analysis, so "4.5%" should be read as "a small discount that worked", not as an
  optimum.

## Run it

```
python demo.py boss        # one decision, ranked moves, sims/sec
python benchmark.py        # the table above (a few minutes)
python -m unittest discover -s tests   # ~3-5 min: includes full search-vs-baseline matches
```

`demo.py boss` prints one decision, so you can see the search reason rather
than take the table on trust:

```
Scenario: boss
You: Player  HP 3000/3000  pips 0+0p
  vs Frost Tyrant [boss]  HP 3000/3000
Hand: Ember Blade, Fire Blast, Weakness Mark, Spark, Flame Dart, Mend, Flame Dart
  rule: Boss hits back for 350 whenever the player casts a trap
  rule: Under 50% HP the boss gains a +25% blade each round

10,250 simulations in 800 ms (12,812/s)

move                                win%    visits
Spark -> Frost Tyrant             50.8%     4,965
Pass                              49.5%     3,192
Weakness Mark -> Frost Tyrant     48.0%     2,093

Recommended: Spark -> Frost Tyrant
```

The ordering is the interesting part. **Weakness Mark is rated below doing
nothing at all** — it is a trap, and this boss hits back for 350 whenever a
trap is cast, so the debuff costs more than it gains. Nothing told the search
that; it is `rules.py` applied inside the rollouts and priced by the outcome.
The visit counts show where the budget went: 4,965 of 10,250 simulations on
the move it ended up recommending, which is what a converged UCB1 search looks
like when one option is genuinely ahead but not by much.

No dependencies. Python 3.11+.

## Performance notes

Pure Python does ~15-20k simulations/second on one core here. The parent
project needed hundreds of thousands per decision inside a sub-second
budget; that gap closed with two orthogonal steps, both reflected in this
codebase's design:

- **mypyc compilation** (~4-5x/core). The annotations in `engine/` — typed
  containers, `Optional` on nullable node fields, `__reduce__` on the
  frozen dataclass — are what made the engine compile cleanly. Untyped
  containers alone cost most of the speedup.
- **Root parallelism** (`engine/parallel.py`, ~Nx for N workers). Each
  worker runs an independent search with its own RNG; the parent merges
  per-action visit counts and value sums. Independent trees also
  decorrelate exploration noise, so close decisions flip less between
  polls than a single bigger search.

## License

MIT
