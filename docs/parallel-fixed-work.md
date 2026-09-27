# Fixed total work across independent trees

`ParallelMCTS.search` has two explicit modes. The existing time mode gives each
worker the requested time limit. Fixed mode divides one total simulation
allowance across independent trees and starts each tree from a reproducible seed.

```python
import random
from engine import ParallelMCTS
from game.content import SCENARIOS

def main():
    state, _ = SCENARIOS["duel"](random.Random(1))
    state.player.pips = 7
    search = ParallelMCTS(horizon_rounds=5, workers=2)
    try:
        ranked = search.search(
            state, mode="fixed", max_sims=101, max_transitions=503, seed=7
        )
        print(search.last_report)
        for row in ranked:
            print(row.label, row.visits, row.win_rate)
    finally:
        search.close()


if __name__ == "__main__":
    main()
```

Here the two workers receive 51 and 50 simulations, plus 252 and 251 simulated
rounds. Both are ceilings. Each simulation reserves a full five round horizon
before starting, then spends only the rounds it actually completes. A worker
can leave a transition remainder smaller than the horizon. It does not truncate
a rollout or borrow another worker's unused allowance. A terminal root spends
nothing. Zero budgets are valid and do not start processes.

Fixed mode requires a nonnegative integer seed and `max_sims`. It rejects a time
budget. Optional `max_transitions` is another total ceiling, not a replacement
for the simulation ceiling. Time mode rejects these fixed controls instead of
silently ignoring them. The serial `MCTS.search(..., time_budget_ms=None)` path
also disables its clock while retaining its simulation and transition ceilings.

The current `mcts_decider` episode wrapper still offers timed parallel searches
only. Call `ParallelMCTS` directly for this fixed work contract. The existing
episode benchmark and its saved studies keep their original interfaces and data.

## What repeats and what changes

Each worker ID receives a seed derived from SHA256 of
`mcts-root-v1:{seed}:{worker_id}`. The first eight bytes form an unsigned integer
in big endian order. A new search starts fresh trees and RNGs, including when a
pool is reused. Environment outcomes outside search use their own RNG.

Results merge in worker ID order using original action identities. The parent
sums raw visit counts and value sums, then divides once to recover a mean.
Equal means and visits use original card slot and target index as a stable tie
break, with Pass first. A fixed state, seed, worker count, implementation and
runtime reproduce the computational result. Process scheduling changes elapsed
time. Different Python versions or floating point platforms may require separate
verification. Changing worker count changes the collection of independent trees
and can change the selected action. It does not reproduce one larger serial tree.

Opening book priors remain virtual evidence in every independent tree, including
a tree assigned zero simulations. Their visits appear separately in each worker
receipt. Root visits therefore equal completed simulations plus virtual visits.
A prior is not another completed simulation. The published scaling protocol uses
no priors, so that particular comparison has no virtual visits.

## Failures and accounting

`last_report` records assigned and used work, unused allowances, worker seeds,
raw root statistics and stopping reasons. Worker compute duration and parent
elapsed time are separate. Pool startup measures process creation through a
readiness message from every initialized worker. A reused pool has zero startup
for that search. `warmup()` returns `False` on a startup error and `True` on
success. It remains nonthrowing for ordinary startup failures, but no longer
silently changes the configured worker count. A subsequent time search retains
its serial fallback. A fixed search retains its requested allocation and failure
contract. `close()` terminates and joins its owned workers.

Fixed mode raises `ParallelSearchError` if a worker fails, times out or returns an
invalid receipt. It never reruns that allowance serially. A caught worker error
retains completed simulations and completed simulator calls. An interrupted
simulator call is not reported as a completed transition. Its partial tree is
not accepted as a recommendation. If a process disappears before reporting,
its used and unused work are unknown. Aggregate totals then remain `None` while
`known_simulations` and `known_transitions` retain the received counts. In this
failure case `last_sims` is only the known completed count, not a complete total.

`worker_timeout_s` is an operational watchdog for dispatched process work. It is
not a successful time mode result or a hard real time guarantee. A one worker
search executes locally and has no process watchdog. Caller interrupts propagate.
Time mode retains its existing serial fallback and cannot make the same fixed
allowance guarantee.

## Bounded computational comparison

The [scaling protocol](parallel-scaling-protocol.json) specifies three initial
states, three search seeds, 1, 2 and 4 workers, and 12,000 total simulations at a
five round horizon. Each fresh engine runs one cold search and one repeated
search on its existing pool. The runner records all work and root statistics.
These are computational decisions, not complete games or a playing strength
evaluation. The existing benchmark, comparator and transition study remain
separate evidence.

Run only from the reviewed committed tree, with competing rendering and tests
paused. Supply a new output path and an accurate conditions note:

```sh
python tools/run_parallel_scaling.py --output parallel-study.json --conditions "Describe the measurement conditions"
```

The protocol and implementation must be committed before the final comparison.
The runner refuses to overwrite an earlier attempt. It saves every condition
incrementally, including failed or interrupted work. No parameter is changed
because a larger worker count is slower. The cold versus warm comparison includes
the cost of separate process startup. Serialization is a separate in process
payload probe. Neither it nor wall time minus worker compute is a direct measure
of transport latency.
