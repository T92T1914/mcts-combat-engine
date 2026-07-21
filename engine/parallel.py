"""Root-parallel MCTS: one independent search per CPU core, merged at the root.

Python's GIL caps a single MCTS at one core. Root parallelization sidesteps
it with processes: N workers each run a full open-loop search on the same
root state with different RNG seeds, then the parent sums per-action visit
counts and value sums. Statistically this behaves like one search with about
N times the simulations — slightly better, in fact, because independent trees
decorrelate the exploration noise that makes close moves flip between polls.

The pool is persistent (spawned once) and its workers are daemonic, so they
die with the main process. Any pool failure degrades to the single-threaded
search, so a decision is always returned.
"""
from __future__ import annotations

import multiprocessing as mp
import random

from .mcts import MCTS, RankedAction

_worker: MCTS | None = None


def _init(horizon: int) -> None:
    global _worker
    _worker = MCTS(horizon_rounds=horizon)
    _worker.max_sims = 1_000_000          # let the time budget rule


def _search(job):
    state, budget_ms, seed, priors = job
    _worker.rng.seed(seed)
    ranked = _worker.search(state, time_budget_ms=budget_ms, priors=priors)
    # ship raw sufficient statistics; win_rate is re-derived after merging
    return ([(r.action, r.visits, r.win_rate * r.visits) for r in ranked],
            _worker.last_sims)


class ParallelMCTS:
    def __init__(self, horizon_rounds: int = 6, workers: int | None = None):
        cpu = mp.cpu_count() or 8
        self.workers = workers if workers else max(1, min(10, cpu - 2))
        self.horizon = horizon_rounds
        self._pool = None
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

    def _ensure_pool(self):
        if self._pool is None:
            ctx = mp.get_context("spawn")
            self._pool = ctx.Pool(self.workers, initializer=_init,
                                  initargs=(self.horizon,))
        return self._pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.terminate()
            self._pool = None

    def search(self, root_state, time_budget_ms: int = 450,
               priors: dict | None = None) -> list:
        if self.workers <= 1:
            ranked = self._single.search(root_state, time_budget_ms,
                                         priors=priors)
            self.last_sims = self._single.last_sims
            return ranked
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
            ranked = self._single.search(root_state, time_budget_ms,
                                         priors=priors)
            self.last_sims = self._single.last_sims
            return ranked
        merged: dict = {}
        total = 0
        for ranked, sims in results:
            total += sims
            for action, visits, value_sum in ranked:
                v, s = merged.get(action, (0, 0.0))
                merged[action] = (v + visits, s + value_sum)
        self.last_sims = total
        out = [RankedAction(action=a, label=a.describe(root_state),
                            win_rate=(s / v if v else 0.0), visits=v)
               for a, (v, s) in merged.items()]
        out.sort(key=lambda r: (r.win_rate, r.visits), reverse=True)
        return out
