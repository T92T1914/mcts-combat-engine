"""Root-parallel MCTS: one independent search per CPU core, merged at the root.

Python's GIL caps a single MCTS at one core. Root parallelization sidesteps
it with processes: N workers each run a full open-loop search on the same
root state with different RNG seeds, then the parent sums per-action visit
counts and value sums. Statistically this behaves like one search with about
N times the simulations — slightly better, in fact, because independent trees
decorrelate the exploration noise that makes close moves flip between polls.

Root parallelism won over tree parallelism (one shared tree, many workers)
because the search is pure Python: threads would serialize on the GIL, and
sharing a tree across processes would mean locking or shipping it. Independent
trees need no synchronization at all; the price is that workers duplicate each
other's early exploration, which is small next to an N-fold simulation count.

The pool is persistent (spawned once) and its workers are daemonic, so they
die with the main process. Any pool failure degrades to the single-threaded
search, so a decision is always returned.
"""
from __future__ import annotations

import multiprocessing as mp
import random
from collections.abc import Iterable
from multiprocessing.pool import Pool

from .actions import Action
from .mcts import MCTS, RankedAction
from .state import GameState

# What a worker ships back: (action, visits, value_sum) per root action, plus
# its simulation count. Raw sufficient statistics, not win rates, so they add.
WorkerResult = tuple[list[tuple[Action, int, float]], int]

_worker: MCTS | None = None


def _init(horizon: int) -> None:
    global _worker
    _worker = MCTS(horizon_rounds=horizon)
    _worker.max_sims = 1_000_000          # let the time budget rule


def _search(job: tuple[GameState, int, int, dict | None]) -> WorkerResult:
    state, budget_ms, seed, priors = job
    assert _worker is not None            # set by _init in every worker
    _worker.rng.seed(seed)
    ranked = _worker.search(state, time_budget_ms=budget_ms, priors=priors)
    return ([(r.action, r.visits, r.win_rate * r.visits) for r in ranked],
            _worker.last_sims)


def merge_results(results: Iterable[WorkerResult],
                  root_state: GameState) -> tuple[list[RankedAction], int]:
    """Sum visits and value sums per action across workers, then re-derive
    each win rate from the totals.

    Summing sufficient statistics is what makes the merge exact: an
    action's merged mean is the mean over every simulation that tried it in
    any tree, each tree weighted by how often it did. Averaging the workers'
    win rates instead would let a tree that barely looked at an action
    count as much as one that studied it.

    Returns the ranked actions and the total simulation count.
    """
    merged: dict[Action, tuple[int, float]] = {}
    total = 0
    for ranked, sims in results:
        total += sims
        for action, visits, value_sum in ranked:
            v, s = merged.get(action, (0, 0.0))
            merged[action] = (v + visits, s + value_sum)
    out = [RankedAction(action=a, label=a.describe(root_state),
                        win_rate=(s / v if v else 0.0), visits=v)
           for a, (v, s) in merged.items()]
    out.sort(key=lambda r: (r.win_rate, r.visits), reverse=True)
    return out, total


class ParallelMCTS:
    """Root-parallel wrapper with the same ``search()`` shape as :class:`MCTS`.

    ``workers`` defaults to ``cpu_count - 2`` capped at 10, which leaves the
    parent process and the rest of the machine some headroom. Workers are
    spawned rather than forked so the pool behaves identically on every OS.
    With one worker (or no pool) it simply runs the single-process search.
    """

    def __init__(self, horizon_rounds: int = 6, workers: int | None = None):
        cpu = mp.cpu_count() or 8
        self.workers = workers if workers else max(1, min(10, cpu - 2))
        self.horizon = horizon_rounds
        self._pool: Pool | None = None
        self._single = MCTS(horizon_rounds=horizon_rounds)
        self._single.max_sims = 1_000_000
        self._rng = random.Random()
        self.last_sims = 0

    def warmup(self) -> None:
        """Spawn the pool up front so the first real decision isn't slow."""
        if self.workers > 1:
            try:
                self._ensure_pool()
            except Exception:
                self.workers = 1

    def _ensure_pool(self) -> Pool:
        if self._pool is None:
            ctx = mp.get_context("spawn")
            self._pool = ctx.Pool(self.workers, initializer=_init,
                                  initargs=(self.horizon,))
        return self._pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.terminate()
            self._pool = None

    def search(self, root_state: GameState, time_budget_ms: int = 450,
               priors: dict | None = None) -> list[RankedAction]:
        if self.workers <= 1:
            return self._search_single(root_state, time_budget_ms, priors)
        try:
            pool = self._ensure_pool()
            jobs = [(root_state, time_budget_ms,
                     self._rng.randrange(2**31), priors)
                    for _ in range(self.workers)]
            results = pool.map_async(_search, jobs).get(
                timeout=time_budget_ms / 1000.0 * 3 + 20)
        except Exception:
            # dead/hung pool: rebuild lazily next turn, answer now
            self.close()
            return self._search_single(root_state, time_budget_ms, priors)
        out, self.last_sims = merge_results(results, root_state)
        return out

    def _search_single(self, root_state: GameState, time_budget_ms: int,
                       priors: dict | None) -> list[RankedAction]:
        ranked = self._single.search(root_state, time_budget_ms, priors=priors)
        self.last_sims = self._single.last_sims
        return ranked
