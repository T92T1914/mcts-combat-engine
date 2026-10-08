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
between decisions until retirement. Parallel mode rejects `seed`, `max_sims`,
`max_transitions` and `on_work`, including with one worker. For reproducible
fixed parallel work, continue to use `ParallelMCTS` directly as described in
[the fixed work contract](parallel-fixed-work.md).

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

The managed policy preserves the existing action selection, search budgets,
random streams and callbacks. A terminal root and an uncapped empty result
retain the existing Pass action. A transition-capped nonterminal search without
a complete simulation still raises `ValueError`. Mean shaped search values
remain distinct from calibrated win probabilities. This lifecycle interface
adds no search-quality or throughput claim.
