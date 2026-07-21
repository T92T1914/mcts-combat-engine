# mcts-combat-engine

A Monte Carlo Tree Search engine for stochastic, imperfect-information,
turn-based combat — pure Python, zero dependencies, with a toy card-duel
game to prove it plays well.

Extracted and generalized from a larger private project: a real-time
decision-support system I built for an online turn-based strategy game,
where this engine (compiled with mypyc and fanned out across cores)
evaluated 400,000+ simulations per decision against live game states. This
repo is the algorithmic core of that system with an original, self-contained
example game, so every claim here is runnable and testable on any machine
with Python 3.11+.

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
  content.py       a 9-card elemental deck and three scenarios
  baselines.py     random and greedy policies to beat
  runner.py        seed-paired match harness
demo.py            watch one decision with ranked moves
benchmark.py       the table below
tests/             11 tests: mechanics, search sanity, beats-the-baselines
```

The engine knows nothing about the example game's cards or numbers — swap
`game/content.py` for your own content without touching `engine/`.

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

## Run it

```
python demo.py boss        # one decision, ranked moves, sims/sec
python benchmark.py        # the table above (a few minutes)
python -m unittest discover -s tests
```

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
