"""Validate and render the declared transition study without running a game."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("random", "greedy", "one_round (300 transitions)", "mcts (300 transitions)")
SCENARIOS = ("duel", "gauntlet", "boss")
BASES = (7, 42, 99)
ALLOWANCE = 300


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _integer(value: object, name: str, low: int, high: int) -> int:
    _require(type(value) is int and low <= value <= high, f"invalid {name}")
    return value  # type: ignore[return-value]


def _number(value: object, name: str, low: float, high: float) -> float:
    _require(
        type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
        f"invalid {name}",
    )
    return float(value)  # type: ignore[arg-type]


def _close(actual: object, expected: float, name: str) -> None:
    number = _number(actual, name, 0, float("inf"))
    _require(
        math.isclose(number, expected, rel_tol=0, abs_tol=1e-10),
        f"{name} does not reconcile",
    )


def protocol_hash(path: Path) -> str:
    """Match committed text regardless of checkout CRLF or an optional BOM."""
    return hashlib.sha256(path.read_text("utf-8-sig").encode("utf-8")).hexdigest()


def decision_ranges(games: list[dict]) -> list[dict]:
    """Map the runner's ordered decisions to its ordered game records."""
    start = 0
    result = []
    for game in games:
        end = start + game["rounds"]
        result.append(
            {
                "environment_seed": game["environment_seed"],
                "policy_seed": game["policy_seed"],
                "start_index": start,
                "stop_index": end,
            }
        )
        start = end
    return result


def assemble_report(
    runs: list[dict],
    *,
    protocol_sha256: str,
    source_revision: str,
    source_hashes: dict,
    evaluation: dict,
) -> dict:
    """Retain raw runs and add explicit half-open game/decision index ranges.

    No outcome is evaluated here. The ranges follow the runner's serial game
    order and round counts. They do not independently observe a decision.
    """
    retained = copy.deepcopy(runs)
    for run in retained:
        for row in run["results"].values():
            for label in LABELS[2:]:
                result = row[label]
                result["transition_work"]["game_decision_ranges"] = decision_ranges(
                    result["game_results"]
                )
    return {
        "schema_version": 1,
        "protocol_sha256": protocol_sha256,
        "source_revision": source_revision,
        "source_hashes": source_hashes,
        "evaluation": evaluation,
        "runs": retained,
    }


def _validate_games(result: dict, policy_seeds: list[int]) -> int:
    games = result["game_results"]
    _require(len(games) == result["games"] == 5, "missing game records")
    _require(
        [g["environment_seed"] for g in games] == list(range(200, 205)),
        "environment seed drift",
    )
    _require([g["policy_seed"] for g in games] == policy_seeds, "policy seed drift")
    for game in games:
        _integer(game["environment_seed"], "environment seed", 200, 204)
        _integer(game["policy_seed"], "policy seed", 7, 103)
        _integer(game["rounds"], "rounds", 1, 30)
        score = _number(game["score"], "game score", 0, 1)
        terminal = game["terminal_result"]
        _require(
            terminal is None or (type(terminal) in (int, float) and terminal in (0, 1)),
            "invalid terminal result",
        )
        _require(
            type(game["clean_win"]) is bool and game["clean_win"] == (terminal == 1),
            "incorrect clean win",
        )
        if terminal is None:
            _require(game["rounds"] == 30 and score < 1, "invalid unfinished game")
        else:
            _require(score == terminal, "terminal score differs from outcome")
    winners = [g for g in games if g["clean_win"]]
    _integer(result["wins"], "wins", 0, 5)
    _require(result["wins"] == len(winners), "wins do not reconcile")
    _close(result["win_rate"], len(winners) / 5, "win rate")
    _close(result["avg_score"], sum(g["score"] for g in games) / 5, "mean score")
    if winners:
        _close(
            result["avg_rounds_to_win"],
            sum(g["rounds"] for g in winners) / len(winners),
            "winning rounds",
        )
    else:
        _require(result["avg_rounds_to_win"] is None, "no-win rounds must be null")
    return sum(g["rounds"] for g in games)


def _validate_work(result: dict, mcts: bool, rounds: int) -> None:
    work = result["transition_work"]
    records = work["decision_records"]
    _require(len(records) == rounds, "decision count differs from game rounds")
    ranges = decision_ranges(result["game_results"])
    _require(work["game_decision_ranges"] == ranges, "game decision mapping differs")
    for game, span in zip(result["game_results"], ranges, strict=True):
        _require(
            len(records[span["start_index"] : span["stop_index"]]) == game["rounds"],
            "incomplete game decision slice",
        )
    incomplete = []
    for index, record in enumerate(records):
        _require(record["max_transitions"] == ALLOWANCE, "allowance drift")
        used = _integer(record["transitions"], "transitions", 1, ALLOWANCE)
        unused = _integer(
            record["unused_transitions"], "unused transitions", 0, ALLOWANCE
        )
        _require(used + unused == ALLOWANCE, "allowance does not reconcile")
        reasons = record["stop_reasons"]
        _require(
            isinstance(reasons, list)
            and reasons
            and len(reasons) == len(set(reasons))
            and set(reasons)
            <= {"transition_allowance", "time_limit", "simulation_cap"},
            "invalid comparison stop reasons",
        )
        if mcts:
            simulations = _integer(
                record["simulations"], "simulations", 1, ALLOWANCE - 5 + 1
            )
            _require(simulations <= used <= 5 * simulations, "simulation work mismatch")
            exhausted = unused < 5
            _require(
                "simulation_cap" not in reasons,
                "simulation cap cannot bind before the reserved-horizon allowance",
            )
        else:
            actions = _integer(record["actions"], "legal actions", 1, ALLOWANCE)
            intended = ALLOWANCE // actions
            _require(record["intended_sweeps"] == intended, "sweep target drift")
            completed = _integer(record["completed_sweeps"], "sweeps", 1, intended)
            _require(used == actions * completed, "partial or miscounted action sweep")
            _require("simulation_cap" not in reasons, "comparator has simulation cap")
            exhausted = completed == intended
        _require(
            ("transition_allowance" in reasons) == exhausted,
            "allowance stop reason mismatch",
        )
        _require(
            ("time_limit" in reasons) == (not exhausted),
            "time shortfall reason mismatch",
        )
        if not exhausted:
            incomplete.append(index)
    _require(work["incomplete_decisions"] == incomplete, "hidden or false shortfalls")
    if mcts:
        search = result["search_work"]
        _require(
            search["decision_simulations"] == [r["simulations"] for r in records],
            "simulation arrays disagree",
        )
        _require(
            search["below_requested_simulations"] is None,
            "transition study is mislabeled fixed-simulation work",
        )
    else:
        one = result["one_round_work"]
        _require(
            one["decision_transitions"] == [r["transitions"] for r in records],
            "comparator arrays disagree",
        )
        _require(
            one["samples_per_action"] is None and one["horizon_rounds"] == 1,
            "comparator mode differs",
        )


def validate(report: dict, protocol: dict, expected_protocol_hash: str) -> None:
    """Reject omitted conditions, contradictory work and unsupported study settings."""
    try:
        _require(
            isinstance(report, dict) and report["schema_version"] == 1,
            "invalid study root",
        )
        _require(
            protocol["scenarios"] == list(SCENARIOS)
            and protocol["environment_seeds"] == list(range(200, 205))
            and protocol["replicates"]
            == [{"search_seed": s, "policy_seed": s} for s in BASES]
            and protocol["shared_allowance"]["transitions_per_decision"] == ALLOWANCE,
            "unsupported protocol controls",
        )
        _require(
            report["protocol_sha256"] == expected_protocol_hash, "protocol hash differs"
        )
        _require(
            re.fullmatch(r"[0-9a-f]{40}", report["source_revision"]) is not None,
            "missing evaluated source revision",
        )
        hashes = report["source_hashes"]
        _require(
            set(hashes) == set(protocol["interface"]["source_paths"])
            and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes.values()),
            "source hash coverage differs",
        )
        _require(len(report["runs"]) == 3, "missing seed-base run")
        for run, seed in zip(report["runs"], BASES, strict=True):
            _require(run["schema_version"] == 3, "unsupported benchmark record")
            settings = run["settings"]
            expected = {
                "games_per_policy": 5,
                "game_seeds": list(range(200, 205)),
                "policy_seeds": list(range(seed, seed + 5)),
                "mode": "transition_allowance",
                "max_simulations": ALLOWANCE,
                "max_transitions": ALLOWANCE,
                "search_seed": seed,
                "search_seed_scope": "reset_per_scenario_then_persistent_across_games",
                "time_limit_ms": 60000,
                "horizon": 5,
                "processes": 1,
                "one_round_samples_per_action": None,
                "one_round_time_limit_ms": 60000,
                "policy_seed_format": "policy-v1:{seed} (Python Random string seed)",
            }
            _require(
                all(settings[k] == v for k, v in expected.items()), "run setting drift"
            )
            _number(run["elapsed_s"], "elapsed seconds", 0, float("inf"))
            _require(
                run["environment"]["python"] and run["environment"]["platform"],
                "missing execution environment",
            )
            _require(
                list(run["results"]) == list(SCENARIOS), "scenario order or set differs"
            )
            for row in run["results"].values():
                _require(list(row) == list(LABELS), "policy order or set differs")
                for label, result in row.items():
                    rounds = _validate_games(result, expected["policy_seeds"])
                    if label in LABELS[2:]:
                        _validate_work(result, label == LABELS[3], rounds)
                    else:
                        _require(
                            "transition_work" not in result,
                            "contextual control incorrectly has search work",
                        )
        _close(
            report["evaluation"]["benchmark_elapsed_seconds"],
            sum(r["elapsed_s"] for r in report["runs"]),
            "total elapsed time",
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"malformed transition study: {exc}") from exc


def render(report: dict) -> str:
    """Render every cell. The caller validates the retained data first."""
    lines = [
        "# Transition allowance comparison",
        "",
        "This study gives MCTS and one-round action enumeration the same allowance "
        "of 300 forward simulator transitions per decision. Whole simulations and "
        "whole equal-action sweeps can leave different unused remainders. Random "
        "and damage-only greedy remain contextual controls with no sampled "
        "forward search.",
        "",
        "## Method",
        "",
        "The [protocol](transition-comparison-protocol.json) was declared before "
        "outcomes. The allowance is a bounded engineering choice, not a tuned value. "
        "MCTS uses a five-round horizon. The comparator evaluates one-round "
        "successors using the same starting random seed for every candidate in a "
        "sweep. Both use the existing simulator and heuristic, so neither is "
        "independent ground truth.",
        "",
        "Environment seeds 200 through 204 are reused across policy/search seed "
        "bases 7, 42 and 99. These are five environments per scenario, not 15 "
        "independent trials. Policy and environment RNGs are separate. Search starts "
        "fresh for each scenario and continues across its five games. Different "
        "actions can consume different random draws even with the same initial seed.",
        "",
        "```sh",
    ]
    for seed in BASES:
        lines.append(
            f"python benchmark.py 5 --transitions 300 --seed {seed} "
            f"--policy-seed {seed} --game-seed 200 --json seed-{seed}.json"
        )
    lines += [
        "python tools/render_transition_comparison.py --check",
        "```",
        "",
        "The last command validates retained data and checks this report. It does "
        "not run the experiment. MCTS and one-round enumeration each have a "
        "60-second safety cap per decision, checked between complete units. "
        "The cap is not a hard deadline.",
        "",
        "## Every measured condition",
        "",
        "Clean wins out of five. These descriptive counts carry no significance "
        "test, confidence interval or general ranking claim.",
        "",
        "| Scenario | Seed base | Random | Greedy | One round | MCTS |",
        "|---|---|---|---|---|---|",
    ]
    rows = [
        (name, run["settings"]["search_seed"], row)
        for run in report["runs"]
        for name, row in run["results"].items()
    ]
    for name, seed, row in rows:
        cells = " | ".join(f"{row[p]['wins']}/5" for p in LABELS)
        lines.append(f"| {name} | {seed} | {cells} |")
    for field, description in (
        (
            "avg_score",
            "Mean shaped score includes partial credit and is not a win probability.",
        ),
        (
            "avg_rounds_to_win",
            "Average rounds conditional on a clean win. A dash means no win.",
        ),
    ):
        lines += [
            "",
            description,
            "",
            "| Scenario | Seed base | Random | Greedy | One round | MCTS |",
            "|---|---|---|---|---|---|",
        ]
        for name, seed, row in rows:
            cells = " | ".join(
                "-" if row[p][field] is None else f"{row[p][field]:.4f}" for p in LABELS
            )
            lines.append(f"| {name} | {seed} | {cells} |")
    lines += [
        "",
        "## Actual work and unfinished games",
        "",
        "| Scenario | Seed base | Policy | Decisions | Used transitions | "
        "Unused allowance | Used min/max | Complete units | Time shortfalls |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    shortfalls = 0
    for name, seed, row in rows:
        for label in LABELS[2:]:
            work = row[label]["transition_work"]
            records = work["decision_records"]
            used = [r["transitions"] for r in records]
            unit = "simulations" if label == LABELS[3] else "completed_sweeps"
            incomplete = len(work["incomplete_decisions"])
            shortfalls += incomplete
            lines.append(
                f"| {name} | {seed} | {label.split()[0]} | {len(records)} | "
                f"{sum(used)} | {sum(r['unused_transitions'] for r in records)} | "
                f"{min(used)}/{max(used)} | {sum(r[unit] for r in records)} | "
                f"{incomplete} |"
            )
    lines += [
        "",
        "Complete units mean MCTS simulations or comparator sweeps, respectively. "
        "MCTS reserves a whole horizon before another simulation. The comparator "
        "requires one transition for every legal candidate before another sweep. "
        "Unused remainders alone are not time shortfalls.",
        "",
        f"Recorded time shortfalls: {shortfalls}. "
        + (
            "Those decisions did not complete the available allowance and remain "
            "in the outcomes below."
            if shortfalls
            else "Every decision reached its ordinary allowance stop."
        ),
        "",
        "| Scenario | Seed base | Policy | Environment seed | Result | Rounds |",
        "|---|---|---|---|---|---|",
    ]
    unfinished = 0
    for name, seed, row in rows:
        for label in LABELS:
            for game in row[label]["game_results"]:
                if game["terminal_result"] is None:
                    unfinished += 1
                    lines.append(
                        f"| {name} | {seed} | {label.split()[0]} | "
                        f"{game['environment_seed']} | unfinished | {game['rounds']} |"
                    )
    if not unfinished:
        lines.append("| All recorded games | - | - | - | terminal | - |")
    env = report["runs"][0]["environment"]
    elapsed = report["evaluation"]["benchmark_elapsed_seconds"]
    lines += [
        "",
        "An unfinished game reached the 30-round limit. It is neither a clean "
        "win nor a loss. Every terminal loss and win is retained in the JSON as well.",
        "",
        "## Evidence and limits",
        "",
        f"Evaluated source: `{report['source_revision']}`. The three serial runs "
        f"took {elapsed:.2f} seconds in the benchmark on Python {env['python']}, "
        f"{env['platform']}. This records the environment, not a policy "
        "speed comparison.",
        "",
        "The [retained JSON](transition-comparison-results.json) keeps all 180 "
        "game records, actual seeds, terminal results, exact decision work, stop "
        "reasons and half-open decision ranges for each game. Source hashes use "
        "UTF-8 text with LF newlines and no BOM. The [earlier study]"
        "(comparison-results.md) remains unchanged.",
        "",
        "Equal transition allowances do not equalize CPU time, memory or cloning "
        "overhead. Total work also depends on game length and whole-unit remainders. "
        "The small fixed environment set and repeated conditions do not establish "
        "general playing strength. The new environment set also prevents treating "
        "this as a controlled before/after improvement over the earlier study.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--data", type=Path, default=ROOT / "docs/transition-comparison-results.json"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/transition-comparison-results.md"
    )
    args = parser.parse_args()
    protocol_path = ROOT / "docs/transition-comparison-protocol.json"
    try:
        _require(
            args.output.resolve() not in {args.data.resolve(), protocol_path.resolve()},
            "output must differ from retained data and protocol inputs",
        )
        protocol = json.loads(protocol_path.read_text("utf-8-sig"))
        report = json.loads(args.data.read_text("utf-8-sig"))
        validate(report, protocol, protocol_hash(protocol_path))
        text = render(report)
        if args.check:
            _require(
                args.output.read_text("utf-8") == text,
                "transition report differs from retained data",
            )
        else:
            args.output.write_text(text, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Transition study: {exc}\n")
    print("Transition study validates and report matches retained data.")


if __name__ == "__main__":
    main()
