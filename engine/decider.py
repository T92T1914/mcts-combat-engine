"""Callable MCTS policies with explicit ownership of search resources."""
from __future__ import annotations

import random
from collections.abc import Callable
from types import TracebackType

from .actions import Action
from .mcts import MCTS
from .parallel import ParallelMCTS, _cleanup_note
from .state import GameState


class MCTSDecider:
    """Own an MCTS policy until explicit close or context exit.

    Calls retain the ``(state, rng) -> Action`` policy interface. The supplied
    policy RNG is unused, as before. Search owns a separate random stream.
    Successful close is permanent and idempotent, including an unused or
    serial policy. Failed retirement blocks decisions and context entry until
    an explicit close retry succeeds. It never starts another search.

    A context preserves its original body exception if cleanup also fails.
    Cleanup diagnostics are best effort. If retirement already failed inside
    the body, exit leaves it pending for explicit retry. A successful body
    cannot hide a cleanup failure. This owner is for sequential calls, not
    concurrent search and close. Process retirement has the underlying
    engine's operating-system limits and no hard completion deadline.
    """

    def __init__(self, budget_ms: int = 300, horizon: int = 5,
                 parallel: bool = False, workers: int | None = None,
                 seed: int | None = None, max_sims: int | None = None, *,
                 on_search: Callable[[int], None] | None = None,
                 max_transitions: int | None = None,
                 on_work: Callable[[dict], None] | None = None) -> None:
        if parallel and (seed is not None or max_sims is not None
                         or max_transitions is not None or on_work is not None):
            raise ValueError("seed, max_sims, max_transitions and on_work "
                             "require single-process search "
                             "(parallel=False)")
        engine: MCTS | ParallelMCTS = (
            ParallelMCTS(horizon_rounds=horizon, workers=workers)
            if parallel else MCTS(horizon_rounds=horizon,
                                  max_transitions=max_transitions))
        if max_transitions is not None and max_transitions < horizon:
            raise ValueError("transition allowance must fund at least "
                             "one complete horizon")
        if isinstance(engine, MCTS):
            engine.max_sims = max_sims if max_sims is not None else 1_000_000
            if seed is not None:
                engine.rng = random.Random(seed)
        self._engine = engine
        self._budget_ms = budget_ms
        self._max_transitions = max_transitions
        self._on_search = on_search
        self._on_work = on_work
        self._closed = False
        self._cleanup_pending = False

    def _retirement_pending(self) -> bool:
        return self._cleanup_pending or (
            not isinstance(self._engine, MCTS)
            and self._engine._retirement_pending)

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("MCTS decider is closed.")
        if self._retirement_pending():
            raise RuntimeError("Decider retirement is incomplete. "
                               "Retry close() first.")

    def __call__(self, state: GameState, rng: random.Random) -> Action:
        self._require_open()
        engine = self._engine
        ranked = engine.search(state, time_budget_ms=self._budget_ms)
        if self._on_search is not None:
            self._on_search(engine.last_sims)
        if self._on_work is not None:
            assert isinstance(engine, MCTS)
            self._on_work({"max_transitions": self._max_transitions,
                           "transitions": engine.last_transitions,
                           "unused_transitions": engine.last_unused_transitions,
                           "simulations": engine.last_sims,
                           "stop_reasons": list(engine.last_stop_reasons)})
        if (self._max_transitions is not None and not ranked
                and not state.is_terminal()):
            raise ValueError("search stopped before a complete simulation")
        return ranked[0].action if ranked else Action(card_idx=None)

    def close(self) -> None:
        """Retire owned workers, or retry a failed retirement explicitly.

        A successful call permanently closes this policy. An error retains
        ownership and refuses new decisions, even if the caller catches it.
        """
        if self._closed:
            return
        self._cleanup_pending = True
        if not isinstance(self._engine, MCTS):
            self._engine.close()
        self._closed = True
        self._cleanup_pending = False

    def __enter__(self) -> MCTSDecider:
        self._require_open()
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc_value: BaseException | None,
                 traceback: TracebackType | None) -> None:
        if self._retirement_pending():
            if exc_value is None:
                raise RuntimeError("Decider retirement is incomplete. "
                                   "Retry close() first.")
            try:
                exc_value.add_note("Decider retirement is incomplete. "
                                   "Retry close() first.")
            except BaseException:
                pass
            return
        try:
            self.close()
        except BaseException as cleanup:
            if exc_value is None:
                raise
            _cleanup_note(exc_value, cleanup)


def mcts_decider(budget_ms: int = 300, horizon: int = 5,
                 parallel: bool = False, workers: int | None = None,
                 seed: int | None = None, max_sims: int | None = None, *,
                 on_search: Callable[[int], None] | None = None,
                 max_transitions: int | None = None,
                 on_work: Callable[[dict], None] | None = None) -> MCTSDecider:
    """Build a managed MCTS policy. Serial search is the default.

    For deterministic serial work, pass both ``seed`` and ``max_sims`` with
    a time allowance sufficient to finish. A seed alone cannot fix a count
    stopped by the clock. Parallel mode remains timed only and rejects seed,
    simulation and transition controls, even with one worker. ``on_search``
    receives completed simulations after each successful search, including
    one stopped by its time limit. ``on_work`` and transition allowances are
    serial only. A capped nonterminal call without a complete simulation
    raises instead of choosing Pass. Other empty results retain Pass.

    Use ``with mcts_decider(...) as choose`` or explicitly call ``close()``.
    The returned policy remains callable until successful retirement, then
    rejects further decisions. Failed cleanup remains visible and retryable.
    The installed factory imports no worked-example content.
    """
    return MCTSDecider(
        budget_ms, horizon, parallel, workers, seed, max_sims,
        on_search=on_search, max_transitions=max_transitions, on_work=on_work)
