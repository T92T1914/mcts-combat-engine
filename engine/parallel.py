"""Root-parallel MCTS: one independent search per CPU core, merged at the root.

Python's GIL caps a single MCTS at one core. Root parallelization sidesteps
it with processes: N workers each run a full open-loop search on the same
root state with different RNG seeds, then the parent sums per-action visit
counts and value sums. Workers explore independently, so this is not
statistically equivalent to one larger search. Each worker builds its own
tree and repeats some early exploration. Decision quality depends on the
scenario and the budget; combining workers does not guarantee a better move.

Root parallelism won over tree parallelism (one shared tree, many workers)
because the search is pure Python: threads would serialize on the GIL, and
sharing a tree across processes would mean locking or shipping it. Independent
trees need no synchronization at all; the price is that workers duplicate each
other's early exploration. The benchmarks need to measure that tradeoff.

The pool persists until close(). Time mode retains its serial fallback.
Fixed mode never retries work after an error. It raises with an accounting
record because a lost worker may already have spent its allowance.
"""
from __future__ import annotations

import hashlib
import math
import multiprocessing as mp
import random
import time
from collections.abc import Iterable
from dataclasses import dataclass
from multiprocessing.pool import Pool

from .actions import Action, is_legal_action, legal_actions
from .mcts import MCTS, RankedAction, _validate_nonnegative_finite, _validate_priors
from .state import GameState

# What a worker ships back: (action, visits, value_sum) per root action, plus
# its simulation count. Raw sufficient statistics, not win rates, so they add.
WorkerResult = tuple[list[tuple[Action, int, float]], int]


def _integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _cleanup_note(error: BaseException, cleanup: BaseException) -> None:
    """Cleanup diagnostics must not replace the failure being reported."""
    try:
        error.add_note(f"Owned cleanup also raised {type(cleanup).__name__}.")
    except BaseException:
        pass


def allocate(total: int, workers: int) -> tuple[int, ...]:
    """Give the first remainder worker IDs one extra unit, with no lost units."""
    _integer(total, "total")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    quotient, remainder = divmod(total, workers)
    return tuple(quotient + (i < remainder) for i in range(workers))


def worker_seed(seed: int, worker_id: int) -> int:
    """Versioned seeds depend only on the explicit seed and stable worker ID."""
    _integer(seed, "seed")
    _integer(worker_id, "worker_id")
    payload = f"mcts-root-v1:{seed}:{worker_id}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


@dataclass(frozen=True)
class WorkerJob:
    worker_id: int
    state: GameState
    horizon: int
    seed: int
    max_sims: int
    max_transitions: int | None
    priors: dict | None


@dataclass(frozen=True)
class WorkerReceipt:
    worker_id: int
    seed: int
    assigned_simulations: int
    assigned_transitions: int | None
    status: str
    simulations: int | None
    transitions: int | None
    unused_simulations: int | None
    unused_transitions: int | None
    virtual_visits: int | None
    stop_reasons: tuple[str, ...]
    statistics: tuple[tuple[Action, int, float], ...] = ()
    elapsed_s: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class FixedWorkReport:
    seed: int
    max_simulations: int
    max_transitions: int | None
    workers: tuple[WorkerReceipt, ...]
    complete: bool
    simulations: int | None
    transitions: int | None
    known_simulations: int
    known_transitions: int
    unused_simulations: int | None
    unused_transitions: int | None
    elapsed_s: float
    pool_startup_s: float


class ParallelSearchError(RuntimeError):
    """A fixed search failed without retrying or hiding its partial work."""

    def __init__(self, report: FixedWorkReport):
        self.report = report
        super().__init__("Fixed search incomplete. Inspect last_report for known "
                         "and unreported work. No allowance was retried.")


def _unreported(job: WorkerJob, status: str, error: str) -> WorkerReceipt:
    known = status == "not_started"
    return WorkerReceipt(
        job.worker_id, job.seed, job.max_sims, job.max_transitions, status,
        0 if known else None, 0 if known else None,
        job.max_sims if known else None, job.max_transitions if known else None,
        0 if known else None, (status,), error=error)


def _fixed_search(job: WorkerJob) -> WorkerReceipt:
    """Run one independent tree with no clock based stopping rule."""
    start = time.perf_counter()
    engine = MCTS(horizon_rounds=job.horizon, max_sims=job.max_sims,
                  max_transitions=job.max_transitions, rng=random.Random(job.seed))
    error = None
    try:
        engine.search(job.state, time_budget_ms=None, priors=job.priors)
        status = "completed"
        reasons = engine.last_stop_reasons
        statistics = tuple(engine.last_root_statistics)
        virtual = sum(v for _, v, _ in statistics) - engine.last_sims
    except Exception as exc:
        # Simulator calls that returned and fully backed up simulations remain
        # known. Partial tree statistics are not accepted as a recommendation.
        status, reasons, statistics, virtual = "failed", ("worker_error",), (), None
        error = type(exc).__name__
    return WorkerReceipt(
        job.worker_id, job.seed, job.max_sims, job.max_transitions, status,
        engine.last_sims, engine.last_transitions,
        job.max_sims - engine.last_sims,
        (job.max_transitions - engine.last_transitions
         if job.max_transitions is not None else None),
        virtual, reasons, statistics, time.perf_counter() - start, error)

_worker: MCTS | None = None


def _init(horizon: int, ready=None) -> None:
    global _worker
    _worker = MCTS(horizon_rounds=horizon)
    _worker.max_sims = 1_000_000          # let the time budget rule
    if ready is not None:
        ready.put(None)


def _search(job: tuple[GameState, float, int, dict | None]) -> WorkerResult:
    state, budget_ms, seed, priors = job
    assert _worker is not None            # set by _init in every worker
    _worker.rng.seed(seed)
    _worker.search(state, time_budget_ms=budget_ms, priors=priors)
    return (_worker.last_root_statistics, _worker.last_sims)


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
    merged: dict[Action, tuple[int, list[float]]] = {}
    total = 0
    for ranked, sims in results:
        total += sims
        for action, visits, value_sum in ranked:
            v, sums = merged.get(action, (0, []))
            sums.append(value_sum)
            merged[action] = (v + visits, sums)
    out = [RankedAction(action=a, label=a.describe(root_state),
                        win_rate=(math.fsum(sums) / v if v else 0.0), visits=v)
           for a, (v, sums) in merged.items()]
    out.sort(key=lambda r: (-r.win_rate, -r.visits,
                           -1 if r.action.card_idx is None else r.action.card_idx,
                           -1 if r.action.target_idx is None else r.action.target_idx))
    return out, total


def _validate_timed_results(results: list[WorkerResult], root_state: GameState,
                            workers: int, priors: dict | None) -> None:
    """Validate the entire returned batch before merging any timed statistics."""
    if type(results) is not list or len(results) != workers:
        raise ValueError("Invalid timed worker result batch")
    legal = set(legal_actions(root_state))
    virtual = 0
    if priors:
        for action in legal:
            if action.card_idx is not None:
                name = root_state.hand[action.card_idx].name
                prior = priors.get(name) if name else None
                if prior:
                    virtual += min(30, 3 * prior[0])
    for result in results:
        if type(result) is not tuple or len(result) != 2:
            raise ValueError("Invalid timed worker result")
        statistics, sims = result
        if type(statistics) is not list:
            raise ValueError("Invalid timed worker result")
        try:
            _integer(sims, "timed worker simulations")
            actions = set()
            visits_total = 0
            for row in statistics:
                if type(row) is not tuple or len(row) != 3:
                    raise ValueError("Invalid timed worker result")
                action, visits, value_sum = row
                if (not isinstance(action, Action)
                        or not is_legal_action(root_state, action)
                        or action not in legal or action in actions):
                    raise ValueError("Invalid timed worker result")
                _integer(visits, "timed worker visits")
                _validate_nonnegative_finite(value_sum, "timed worker value sum")
                if value_sum > visits:
                    raise ValueError("Invalid timed worker result")
                actions.add(action)
                visits_total += visits
            if visits_total != sims + virtual:
                raise ValueError("Invalid timed worker result")
        except (TypeError, ValueError, AttributeError, OverflowError) as error:
            raise ValueError("Invalid timed worker result") from error


class ParallelMCTS:
    """Root-parallel wrapper with the same ``search()`` shape as :class:`MCTS`.

    ``workers`` defaults to ``cpu_count - 2`` capped at 10, which leaves the
    parent process and the rest of the machine some headroom. Workers are
    spawned rather than forked so the pool behaves identically on every OS.
    With one worker (or no pool) it simply runs the single-process search.
    """

    def __init__(self, horizon_rounds: int = 6, workers: int | None = None):
        if workers is not None and (
                not isinstance(workers, int) or isinstance(workers, bool)
                or workers < 1):
            raise ValueError("workers must be a positive integer or None")
        cpu = mp.cpu_count() or 8
        self.workers = workers if workers is not None else max(1, min(10, cpu - 2))
        self.horizon = horizon_rounds
        self._pool: Pool | None = None
        self._retirement_pending = False
        self._single = MCTS(horizon_rounds=horizon_rounds)
        self._single.max_sims = 1_000_000
        self._rng = random.Random()
        self.last_sims = 0
        self.last_report: FixedWorkReport | None = None
        self.last_pool_startup_s = 0.0

    def warmup(self) -> bool:
        """Report startup success without changing the requested worker count.

        Time mode still handles a startup failure with its serial fallback.
        A later fixed search retains its configured allocation and error policy.
        """
        if self.workers > 1:
            try:
                self._ensure_pool()
            except Exception:
                return False
        return True

    def _ensure_pool(self) -> Pool:
        if self._retirement_pending:
            raise RuntimeError("Pool retirement is incomplete. Retry close() first.")
        if self._pool is None:
            ctx = mp.get_context("spawn")
            ready = ctx.Queue()
            start = time.perf_counter()
            failure = None
            try:
                self._pool = ctx.Pool(self.workers, initializer=_init,
                                      initargs=(self.horizon, ready))
                deadline = start + 30
                for _ in range(self.workers):
                    ready.get(timeout=max(0, deadline - time.perf_counter()))
            except BaseException as exc:
                failure = exc
                self._close_after_error(exc)
                raise
            finally:
                self.last_pool_startup_s = time.perf_counter() - start
                try:
                    ready.close()
                    ready.join_thread()
                except BaseException as cleanup:
                    if failure is None:
                        self._close_after_error(cleanup)
                        raise
                    _cleanup_note(failure, cleanup)
        return self._pool

    def close(self) -> None:
        if self._pool is not None:
            # A failed terminate can leave live handlers. Joining that pool
            # could block, so retain ownership for an explicit close retry.
            self._retirement_pending = True
            self._pool.terminate()
            self._pool.join()
            self._pool = None
            self._retirement_pending = False

    def _close_after_error(self, error: BaseException) -> bool:
        if self._retirement_pending:
            try:
                error.add_note("Pool retirement is incomplete. Retry close() first.")
            except BaseException:
                pass
            return False
        try:
            self.close()
        except BaseException as cleanup:
            _cleanup_note(error, cleanup)
            return False
        return True

    def search(self, root_state: GameState, time_budget_ms: float | None = None,
               priors: dict | None = None, *, mode: str = "time",
               max_sims: int | None = None, max_transitions: int | None = None,
               seed: int | None = None,
               worker_timeout_s: float = 60,
               execution: str = "process") -> list[RankedAction]:
        """Use a time budget or explicitly divide fixed total work.

        Time mode defaults to 450 ms and preserves the serial fallback. Fixed
        mode requires ``max_sims`` and ``seed``, forbids a time budget, and
        optionally partitions a total transition ceiling. It never reallocates
        unused work. The worker timeout aborts an operation, not a successful
        timed substitute. ``last_report`` retains that distinction.

        Fixed mode can execute the same forest sequentially in the parent with
        ``execution="sequential"``. Allocation, seeds and merging stay identical.
        This control does not replace the forest with one larger tree. Local
        execution has no process watchdog. Process execution remains the default.
        """
        if self._retirement_pending:
            raise RuntimeError("Pool retirement is incomplete. Retry close() first.")
        self.last_sims = 0
        self.last_report = None
        self.last_pool_startup_s = 0.0
        _validate_priors(priors)
        if mode not in ("time", "fixed"):
            raise ValueError("mode must be 'time' or 'fixed'")
        if execution not in ("process", "sequential"):
            raise ValueError("execution must be 'process' or 'sequential'")
        if mode != "fixed" and execution != "process":
            raise ValueError("sequential execution requires mode='fixed'")
        if mode == "fixed":
            if time_budget_ms is not None:
                raise ValueError("fixed mode cannot use time_budget_ms")
            if max_sims is None or seed is None:
                raise ValueError("fixed mode requires max_sims and seed")
            _integer(max_sims, "max_sims")
            _integer(seed, "seed")
            if max_transitions is not None:
                _integer(max_transitions, "max_transitions")
            _validate_nonnegative_finite(worker_timeout_s, "worker_timeout_s")
            if worker_timeout_s == 0:
                raise ValueError("worker_timeout_s must be positive")
            return self._search_fixed(root_state, max_sims, max_transitions,
                                      seed, priors, worker_timeout_s, execution)
        if max_sims is not None or max_transitions is not None or seed is not None:
            raise ValueError("fixed work controls require mode='fixed'")
        time_budget_ms = 450 if time_budget_ms is None else time_budget_ms
        _validate_nonnegative_finite(time_budget_ms, "time_budget_ms")
        if root_state.is_terminal():
            return []  # avoid even starting a pool for a finished position
        if self.workers <= 1 or time_budget_ms == 0:
            return self._search_single(root_state, time_budget_ms, priors)
        try:
            pool = self._ensure_pool()
            jobs = [(root_state, time_budget_ms,
                     self._rng.randrange(2**31), priors)
                    for _ in range(self.workers)]
            results = pool.map_async(_search, jobs).get(
                timeout=time_budget_ms / 1000.0 * 3 + 20)
            _validate_timed_results(results, root_state, self.workers, priors)
            out, simulations = merge_results(results, root_state)
        except BaseException as exc:
            # dead/hung pool: rebuild lazily next turn, answer now
            retired = self._close_after_error(exc)
            if not isinstance(exc, Exception) or not retired:
                # A caller stop is not permission to begin a serial retry.
                raise
            return self._search_single(root_state, time_budget_ms, priors)
        self.last_sims = simulations
        return out

    def _search_fixed(self, state: GameState, max_sims: int,
                      max_transitions: int | None, seed: int, priors: dict | None,
                      timeout: float, execution: str) -> list[RankedAction]:
        start = time.perf_counter()
        sims = allocate(max_sims, self.workers)
        transitions = (allocate(max_transitions, self.workers)
                       if max_transitions is not None else (None,) * self.workers)
        jobs = [WorkerJob(i, state, self.horizon, worker_seed(seed, i),
                          sims[i], transitions[i], priors)
                for i in range(self.workers)]
        receipts: dict[int, WorkerReceipt] = {}
        pending = {}
        attempted: set[int] = set()
        failure = None
        failure_error = None
        interruption = None
        cleanup_error = None
        try:
            for job in jobs:
                # Zero work and terminal roots need no process. Applying the
                # priors still follows the same independent tree contract.
                if (execution == "sequential" or self.workers == 1
                        or state.is_terminal() or job.max_sims == 0
                        or (job.max_transitions is not None
                            and job.max_transitions < self.horizon)):
                    attempted.add(job.worker_id)
                    receipts[job.worker_id] = _fixed_search(job)
                else:
                    pool = self._ensure_pool()
                    # apply_async may enqueue work before an interrupt prevents
                    # its result handle from reaching this process.
                    attempted.add(job.worker_id)
                    pending[job.worker_id] = pool.apply_async(_fixed_search, (job,))
            deadline = start + timeout
            for worker_id, result in pending.items():
                receipts[worker_id] = result.get(
                    timeout=max(0, deadline - time.perf_counter()))
        except BaseException as exc:
            failure = type(exc).__name__
            failure_error = exc
            if not isinstance(exc, Exception):
                interruption = exc
            try:
                # Retain ready results without waiting again or replaying jobs.
                for worker_id, result in pending.items():
                    if worker_id in receipts:
                        continue
                    try:
                        if result.ready():
                            receipts[worker_id] = result.get(timeout=0)
                    except BaseException as observed:
                        if not isinstance(observed, Exception) and interruption is None:
                            interruption = observed
            finally:
                if not self._retirement_pending:
                    try:
                        self.close()
                    except BaseException as cleanup:
                        cleanup_error = cleanup
        legal = set(legal_actions(state)) if not state.is_terminal() else set()
        for job in jobs:
            record = receipts.get(job.worker_id)
            if record is None:
                status = "unreported" if job.worker_id in attempted else "not_started"
                receipts[job.worker_id] = _unreported(job, status, failure or status)
            else:
                try:
                    valid = self._valid_receipt(record, job, legal)
                except (TypeError, ValueError, AttributeError, OverflowError):
                    valid = False
                if not valid:
                    receipts[job.worker_id] = _unreported(
                        job, "unreported", "InvalidWorkerReceipt")
        ordered = tuple(receipts[i] for i in range(self.workers))
        known_sims = sum(r.simulations or 0 for r in ordered)
        known_transitions = sum(r.transitions or 0 for r in ordered)
        known = all(r.simulations is not None and r.transitions is not None
                    for r in ordered)
        complete = all(r.status == "completed" for r in ordered)
        self.last_sims = known_sims
        self.last_report = FixedWorkReport(
            seed, max_sims, max_transitions, ordered, complete,
            known_sims if known else None, known_transitions if known else None,
            known_sims, known_transitions, max_sims - known_sims if known else None,
            (max_transitions - known_transitions
             if known and max_transitions is not None else None),
            time.perf_counter() - start, self.last_pool_startup_s)
        if interruption is not None:
            if cleanup_error is not None:
                _cleanup_note(interruption, cleanup_error)
            raise interruption
        if not complete:
            error = ParallelSearchError(self.last_report)
            if cleanup_error is not None:
                _cleanup_note(error, cleanup_error)
            else:
                self._close_after_error(error)
            raise error
        if cleanup_error is not None:
            if failure_error is not None:
                _cleanup_note(failure_error, cleanup_error)
                raise failure_error
            raise cleanup_error
        out, _ = merge_results(
            [(list(r.statistics), r.simulations or 0) for r in ordered], state)
        return out

    @staticmethod
    def _valid_receipt(record: WorkerReceipt, job: WorkerJob,
                       legal: set[Action]) -> bool:
        """Do not accept malformed worker output as completed fixed work."""
        if not isinstance(record, WorkerReceipt):
            return False
        if type(record.statistics) is not tuple:
            return False
        if any(type(row) is not tuple or len(row) != 3
               for row in record.statistics):
            return False
        if record.elapsed_s is None:
            return False
        try:
            # Equal numeric aliases do not establish integer work identities.
            for value, name in (
                    (record.worker_id, "worker_id"), (record.seed, "seed"),
                    (record.assigned_simulations, "assigned_simulations"),
                    (record.unused_simulations, "unused_simulations")):
                _integer(value, name)
            if record.assigned_transitions is not None:
                _integer(record.assigned_transitions, "assigned_transitions")
            if record.unused_transitions is not None:
                _integer(record.unused_transitions, "unused_transitions")
            _validate_nonnegative_finite(record.elapsed_s, "elapsed_s")
        except ValueError:
            return False
        if (record.worker_id != job.worker_id or record.seed != job.seed
                or record.assigned_simulations != job.max_sims
                or record.assigned_transitions != job.max_transitions
                or record.status not in ("completed", "failed")):
            return False
        sims, transitions = record.simulations, record.transitions
        if (not isinstance(sims, int) or isinstance(sims, bool)
                or not 0 <= sims <= job.max_sims
                or not isinstance(transitions, int) or isinstance(transitions, bool)
                or not sims <= transitions <= job.max_sims * job.horizon
                or record.unused_simulations != job.max_sims - sims):
            return False
        if (job.max_transitions is not None
                and (transitions > job.max_transitions
                     or record.unused_transitions
                     != job.max_transitions - transitions)):
            return False
        if job.max_transitions is None and record.unused_transitions is not None:
            return False
        if record.status == "failed":
            return (not record.statistics and record.virtual_visits is None
                    and isinstance(record.error, str) and bool(record.error)
                    and record.stop_reasons == ("worker_error",))
        if record.error is not None:
            return False
        reasons = []
        if not legal:
            reasons.append("terminal")
            if sims or transitions or record.statistics:
                return False
        else:
            if (job.max_transitions is not None
                    and job.max_transitions - transitions < job.horizon):
                reasons.append("transition_allowance")
            if sims == job.max_sims:
                reasons.append("simulation_cap")
        expected_virtual = 0
        if job.priors:
            for action in legal:
                if action.card_idx is not None:
                    prior = job.priors.get(job.state.hand[action.card_idx].name)
                    if prior:
                        expected_virtual += min(30, 3 * prior[0])
        if (record.stop_reasons != tuple(reasons) or not reasons
                or not isinstance(record.virtual_visits, int)
                or isinstance(record.virtual_visits, bool)
                or record.virtual_visits != expected_virtual
                or sum(v for _, v, _ in record.statistics)
                != sims + record.virtual_visits):
            return False
        actions = set()
        for action, visits, value_sum in record.statistics:
            # Equality alone accepts bool/float aliases of integer indices.
            if (not isinstance(action, Action)
                    or not is_legal_action(job.state, action)
                    or action not in legal or action in actions
                    or not isinstance(visits, int) or isinstance(visits, bool)
                    or visits < 0 or not math.isfinite(value_sum)
                    or not 0 <= value_sum <= visits):
                return False
            actions.add(action)
        return True

    def _search_single(self, root_state: GameState, time_budget_ms: float,
                       priors: dict | None) -> list[RankedAction]:
        ranked = self._single.search(root_state, time_budget_ms, priors=priors)
        self.last_sims = self._single.last_sims
        return ranked
