# A callable policy that owns its workers

`engine.mcts_decider` returns an `MCTSDecider`. It accepts the existing policy
call, `(state, rng) -> Action`, and owns its search engine until `close()` or
context exit. It is available from the installed `engine` package. The same
factory remains available from `game.baselines` in a checkout.

This complete serial example uses only the installed package and standard
library:

```python
import random
from engine import Card, Combatant, Element, GameState, mcts_decider

state = GameState(
    player=Combatant("Player", Element.EMBER, hp=100, max_hp=100, pips=3),
    enemies=[Combatant("Opponent", Element.FROST, hp=100, max_hp=100)],
    hand=[Card("Hit", pip_cost=1, damage_min=20, damage_max=20)],
)

with mcts_decider(budget_ms=60_000, horizon=2, seed=7, max_sims=20) as choose:
    action = choose(state, random.Random(99))
    print(action.describe(state))
```

The policy RNG remains separate from search randomness and is unused by this
MCTS policy. A fixed search seed and simulation ceiling reproduce serial work
when the clock does not stop it early. `budget_ms` remains a clock limit,
including when `max_sims` is supplied. Existing transition allowances and
`on_search` and `on_work` callbacks retain their behavior.

For a timed parallel policy, use `parallel=True, workers=2`. On Windows,
construct and call it inside a `main()` guarded by
`if __name__ == "__main__":`, and execute the file. The owned pool is reused
between decisions until retirement. The default `mode="time"` retains its
rejection of `seed`, `max_sims`, `max_transitions` and `on_work` in parallel
mode, including with one worker.

## Managed fixed work

Select `parallel=True, mode="fixed", budget_ms=None` and supply nonnegative
integer `seed` and `max_sims` values. Optional `max_transitions` is another
nonnegative total ceiling per decision. Fixed mode refuses a clock budget and
does not select serial search. It uses the existing independent-root allocation,
receipt validation and failure behavior from
[the fixed work contract](parallel-fixed-work.md).

```python
with mcts_decider(
    parallel=True, workers=2, horizon=2, mode="fixed", budget_ms=None,
    seed=7, max_sims=12, max_transitions=24,
) as choose:
    first = choose(state, random.Random(99))
    receipt = choose.last_report
    repeated = choose(state, random.Random(99))
    selected_seed = choose.decide(state, seed=23)
    default_seed_again = choose.decide(state)
```

On Windows run this inside a guarded `main()` in a file. The complete
[installed-package example](../examples/managed_fixed.py) constructs its own
state, prints actions and receipts, and shows refusal after context exit.
It needs only the installed engine and standard library.

Every decision starts fresh trees with a fresh allowance. Ordinary policy calls
reuse seed 7 in this example. `decide(state, seed=23)` selects only that call's
seed. It never changes the configured default or advances a hidden sequence,
whether the call succeeds or fails. Callers who want an advancing sequence
must choose each seed themselves. The policy RNG remains unused.

For a fixed state, seed, worker count, implementation and verified runtime,
repeated computational receipts agree. Elapsed and startup durations can
change. Another worker count changes the forest and may change the action.
Independent trees do not reproduce one larger serial tree. Fixed work does
not establish a production wall-clock deadline. The lower-level process
watchdog remains 60 seconds, and local work with one worker has no process
watchdog.

`last_report` exposes the immutable `FixedWorkReport` from the latest fixed
attempt. Open admission clears it before per-call seed validation or search.
A rejected seed or an attempt that produces no report therefore leaves `None`.
Closed or retirement-pending refusal preserves the previous receipt, as does
successful close. Timed and serial policies have no fixed-work receipt.

In fixed mode `on_work` receives `dataclasses.asdict(last_report)`, a detached
dictionary, whenever an attempt produces a report. This includes an incomplete
worker batch or caller interrupt. Worker statistics contain dictionaries for
their `Action` fields. Unknown work retains `None`, never an invented zero.
After a successful fixed search, `on_work` runs before `on_search`, so a failing
count observer cannot hide the work notification. Serial callback order and
dictionary shape are unchanged. `on_search` is not called for a failed search.

If a search error or caller interrupt and the work callback both raise, the
search error remains primary. A best-effort note names the callback error's
class. A callback failure after a successful search propagates normally, with
the receipt still available. Callbacks do not retry search or advance seeds.

An incomplete fixed batch raises `ParallelSearchError` and returns no action.
Its report retains known counts and unknown totals. No failed allowance is
rerun serially. Zero or below-horizon ceilings are valid accounting requests.
If they fund no complete simulation at a nonterminal root, the policy raises
`ValueError` after reporting the complete zero-work receipt instead of choosing
Pass. A terminal root retains Pass with zero work. Pool reuse and explicit
cleanup follow the same managed contract below.

## Closing and recovery

Closing an unused or serial policy is valid. A successful `close()` is permanent
for that policy. Repeated close does nothing, while another decision or context
entry raises `RuntimeError` before search or callbacks. Create a new policy to
start another lifetime. The underlying `ParallelMCTS` interface retains its
existing ability to create a fresh pool after successful close.

If termination or joining raises, the policy retains its engine and blocks new
decisions and context entry. The cleanup error remains visible. An explicit
`choose.close()` retries retirement. Only successful retirement finishes the
policy lifetime. The handle remaining owned does not prove that workers have
physically exited, and operating-system retirement has no hard completion
deadline.

A context retires the policy when its body finishes. If its body raises and
retirement also fails, the original exception object propagates. A best-effort
exception note records the cleanup class without converting either exception
to text. A failed diagnostic cannot replace the original error. If the body
succeeded, a cleanup failure propagates normally.

When a search or explicit close already left retirement incomplete inside the
body, context exit keeps that state pending for an explicit retry. It does not
repeat the failed cleanup automatically. If the body caught the earlier failure
and then completed, exit still raises `RuntimeError` requesting that retry.

Keep the policy object when handling a retirement failure so that `close()` can
be retried. Calls, context entry and close are intended to occur sequentially.
There is no concurrent search/close contract or finalizer that substitutes for
explicit ownership.

## Search behavior

Timed mode preserves the existing action selection, search budgets,
random streams and callbacks. A terminal root and an uncapped empty result
retain the existing Pass action. A transition-capped nonterminal search without
a complete simulation still raises `ValueError`. Mean shaped search values
remain distinct from calibrated win probabilities. This lifecycle interface
adds no search-quality or throughput claim.
