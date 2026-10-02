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

Fixed mode also accepts `execution="sequential"`. It runs the same independent
roots one after another in the parent process. `workers` still sets the number
of roots, their allowance splits and their seeds. The jobs, receipt validation
and merge are shared with the default `execution="process"` path. This is an
execution control, not a different search policy or a retry after a worker failure.
Time mode rejects sequential execution. Local execution has no process watchdog.
The setting does not change the existing report shape or default API behavior.

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

If termination or joining raises, the pool handle remains owned and new searches
are refused until an explicit `close()` retry succeeds. A failed termination
does not start a potentially blocking join. Timed search does not begin its
serial fallback while retirement is unresolved. Cleanup errors do not replace
the original caller stop, and fixed work still retains received counts and
unknown allowances in `last_report`. Diagnostic notes are best effort.

Fixed mode raises `ParallelSearchError` if a worker fails, times out or returns an
invalid receipt. It never reruns that allowance serially. A caught worker error
retains completed simulations and completed simulator calls. An interrupted
simulator call is not reported as a completed transition. Its partial tree is
not accepted as a recommendation. If a process disappears before reporting,
its used and unused work are unknown. Aggregate totals then remain `None` while
`known_simulations` and `known_transitions` retain the received counts. In this
failure case `last_sims` is only the known completed count, not a complete total.

Worker actions use the simulator's index and target validation before merging.
Boolean and floating point indices are refused even when Python compares them
equal to a legal integer action. A reward sum that cannot be represented for
the finite-value check also makes the receipt unreported. These refusals retain
the incomplete-work report and do not start another search.

Root statistics must remain a plain built-in tuple of plain three-field tuple
rows. The parent checks both structures before reading visit counts or validating
actions. An iterator could be consumed by the first check and disappear before
validation or merging. A tuple subclass could also return different values each
time it is read. Iterators, mutable collections and tuple subclasses become
unreported work without consuming their entries.

The receipt's worker identity, seed, assigned allowances and unused counts must
also retain integer types. Numeric aliases such as `False` for zero or `2.0` for
two are not accepted just because they compare equal. An absent transition ceiling
requires an absent unused-transition count. Reported compute duration must be
finite and nonnegative. Completed receipts have no error, while failed receipts
retain a nonempty error name and no usable virtual visits or root statistics.
Contradictory receipts become unreported work, preserving other workers' valid
counts without retrying the uncertain allowance.

`worker_timeout_s` is an operational watchdog for dispatched process work. It is
not a successful time mode result or a hard real time guarantee. A one worker
search executes locally and has no process watchdog. Caller interrupts during
pool readiness, dispatch or result collection retire the owned pool before
propagating. During fixed dispatch or result collection, valid ready receipts
remain in `last_report` without waiting again.
An attempted dispatch whose result handle was not returned has unknown work,
because interruption can occur after enqueueing. Later unattempted jobs remain
`not_started`. Interrupted inline work also remains unknown when no receipt was
returned. None of these allowances is retried. If every receipt is already ready,
the computational report can be complete while the interrupt still propagates
instead of returning a recommendation. Time mode retains its serial fallback
for ordinary worker failures, but a caller interrupt does not start that retry.
Its work still cannot make the same fixed allowance guarantee. These cleanup
guards do not cover later receipt validation or result merging. A second caller
interrupt during termination or joining can also leave retirement incomplete.
The original failure remains primary, but retained ownership is not proof that
the workers have physically exited. Cleanup can still block if an operating
system call does not return, and an explicit retry has no hard time guarantee.

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

The [retained first study](parallel-scaling-results.md) completed the 54 declared
searches on the committed implementation. Its report and raw data preserve every
cell, the source revision and the shared machine conditions. Validate or render
those saved data without running another experiment:

```sh
python tools/render_parallel_scaling.py --check
python tools/render_parallel_scaling.py
python tools/build_site.py
```

Both report formats use the same validated data. The public HTML uses the
project's Auto, Clair and Obscur controls, local Inter faces and readable system
fallback. Public visitors do not automatically receive Inter. The site manifest
records the presentation revision separately from the measured source revision.

## Same forest execution control

The separate [execution protocol](same-forest-protocol.json) holds the forest
fixed while comparing sequential execution with cold and initialized process
pools. It uses six conditions and 18 executions, with one search seed and two
root counts for each of the three scenarios. Exact computational equality is a
gate for reporting paired times. Seeds, raw statistics, assigned and unused
work, stopping reasons and ranked actions must agree. Only elapsed fields are
excluded from that comparison.

Its warm phase starts an initialized pool before the timer, without an extra
search. That differs from the second search on a reused pool in the original
scaling study. The runner retains preparation time separately and saves a
running cell before starting work. It stops on a failure or identity mismatch
and preserves the first attempt. The [retained result](same-forest-results.md)
completed all 18 executions with identical computational receipts in all six
conditions. The earlier measurements, protocol and reports remain unchanged.

```sh
python tools/run_same_forest.py --output same-forest-study.json --conditions "Describe the observed measurement conditions"
```

Commit and review this implementation and protocol before collecting results.
Pause competing owned workloads during the measurement window and use a fresh
output path. The narrow comparison can distinguish execution effects from
changing tree count in these conditions. It does not establish playing strength,
general scaling or pure communication latency.
