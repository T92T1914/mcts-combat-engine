"""Validate and present the retained process study without running search."""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("duel", "gauntlet", "boss")
SEEDS = (7, 42, 99)
ORDERS = ((1, 2, 4), (2, 4, 1), (4, 1, 2))
PHASES = ("cold", "warm")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_text("utf-8-sig").encode()).hexdigest()


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, "invalid work count")
    return value


def number(value, low=0):
    require(
        type(value) in (float, int) and math.isfinite(value) and value >= low,
        "invalid numeric observation",
    )
    return value


def action_key(action):
    require(set(action) == {"card_idx", "target_idx"}, "invalid action identity")
    for value in action.values():
        if value is not None:
            integer(value, 0, 1000)
    return tuple(
        -1 if action[k] is None else action[k] for k in ("card_idx", "target_idx")
    )


def computational(cell):
    """Strip only timing from paired receipts, not accounting or root results."""
    report = copy.deepcopy(cell["report"])
    del report["elapsed_s"]
    del report["pool_startup_s"]
    for worker in report["workers"]:
        del worker["elapsed_s"]
    return report, cell["ranked"]


def validate(record, protocol, expected_hash):
    """Accept the complete declared study, with every allowance and mean checked."""
    try:
        require(
            record["schema_version"] == protocol["schema_version"] == 1,
            "unsupported schema",
        )
        require(
            record["protocol"] == protocol["id"] == "parallel-fixed-work-scaling-v1",
            "protocol identity differs",
        )
        require(record["protocol_sha256"] == expected_hash, "protocol hash differs")
        require(
            protocol["scenarios"] == list(SCENARIOS)
            and protocol["search_seeds"] == list(SEEDS)
            and protocol["worker_orders"] == [list(o) for o in ORDERS]
            and protocol["pool_phases"] == list(PHASES)
            and protocol["environment_seed"] == 300
            and protocol["horizon_rounds"] == 5
            and protocol["max_simulations"] == 12000
            and protocol["max_transitions"] == 60000
            and protocol["priors"] is None,
            "unsupported study controls",
        )
        require(record["status"] == "complete", "retained study is not complete")
        require(
            record["source_unchanged_at_end"] is True
            and record["source"]["worktree_clean"] is True,
            "source identity was not stable",
        )
        require(
            re.fullmatch(r"[0-9a-f]{40}", record["source"]["revision"]),
            "missing full evaluation revision",
        )
        hashes = record["source"]["sha256"]
        require(
            hashes["docs/parallel-scaling-protocol.json"] == expected_hash
            and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in hashes.values()),
            "invalid source hashes",
        )
        environment = record["environment"]
        require(
            environment["start_method"] == "spawn"
            and environment["python"]
            and environment["platform"]
            and environment["conditions"],
            "missing measurement conditions",
        )
        expected = [
            (s, seed, w, phase)
            for s in SCENARIOS
            for seed, order in zip(SEEDS, ORDERS, strict=True)
            for w in order
            for phase in PHASES
        ]
        actual = [
            (c["scenario"], c["search_seed"], c["workers"], c["phase"])
            for c in record["cells"]
        ]
        require(actual == expected, "missing, duplicated or reordered condition")
        roots = {}
        for cell in record["cells"]:
            require(
                cell["error"] is None and cell["environment_seed"] == 300,
                "failed condition or changed root seed",
            )
            root_hash = cell["root_pickle_sha256"]
            require(re.fullmatch(r"[0-9a-f]{64}", root_hash), "invalid root hash")
            require(
                roots.setdefault(cell["scenario"], root_hash) == root_hash,
                "root changed between conditions",
            )
            wall = number(cell["elapsed_s"])
            require(wall > 0, "zero wall time")
            probe = cell["serialization_probe"]
            integer(probe["payload_bytes"], 1, 10000000)
            number(probe["encode_s"])
            number(probe["decode_s"])
            require(
                probe["scope"] == "in-process payload control, not actual IPC latency",
                "serialization scope differs",
            )
            report = cell["report"]
            require(
                report["complete"] is True
                and report["seed"] == cell["search_seed"]
                and report["max_simulations"] == 12000
                and report["max_transitions"] == 60000,
                "search contract differs",
            )
            require(len(report["workers"]) == cell["workers"], "missing worker")
            number(report["elapsed_s"])
            startup = number(report["pool_startup_s"])
            require(startup <= wall, "startup exceeds wall time")
            if cell["phase"] == "warm" or cell["workers"] == 1:
                require(startup == 0, "unexpected process startup")
            else:
                require(startup > 0, "missing cold startup measurement")
            merged = {}
            for i, worker in enumerate(report["workers"]):
                sims = 12000 // cell["workers"]
                cap = 60000 // cell["workers"]
                seed_bytes = hashlib.sha256(
                    f"mcts-root-v1:{cell['search_seed']}:{i}".encode("ascii")
                ).digest()
                require(
                    worker["worker_id"] == i
                    and worker["seed"] == int.from_bytes(seed_bytes[:8], "big"),
                    "worker seed differs",
                )
                require(
                    worker["status"] == "completed" and worker["error"] is None,
                    "hidden worker failure",
                )
                require(
                    worker["assigned_simulations"] == sims
                    and worker["assigned_transitions"] == cap
                    and worker["simulations"] == sims
                    and worker["unused_simulations"] == 0
                    and worker["virtual_visits"] == 0,
                    "simulation allowance differs",
                )
                used = integer(worker["transitions"], sims, cap)
                require(
                    worker["unused_transitions"] == cap - used,
                    "unused transitions differ",
                )
                reasons = ["transition_allowance"] if cap - used < 5 else []
                require(
                    worker["stop_reasons"] == reasons + ["simulation_cap"],
                    "stopping reason differs",
                )
                number(worker["elapsed_s"])
                seen, visits = set(), 0
                for action, count, value_sum in worker["statistics"]:
                    key = action_key(action)
                    require(key not in seen, "duplicate root action")
                    seen.add(key)
                    visits += integer(count, 1, sims)
                    require(number(value_sum) <= count, "invalid root value sum")
                    merged.setdefault(key, []).append((count, value_sum))
                require(visits == sims, "root visits do not account for completed work")
            transitions = sum(w["transitions"] for w in report["workers"])
            require(
                report["simulations"] == report["known_simulations"] == 12000
                and report["transitions"] == report["known_transitions"] == transitions
                and report["unused_simulations"] == 0
                and report["unused_transitions"] == 60000 - transitions,
                "aggregate work differs",
            )
            values = {
                key: (sum(n for n, _ in parts), math.fsum(v for _, v in parts))
                for key, parts in merged.items()
            }
            ordered = sorted(
                values, key=lambda k: (-values[k][1] / values[k][0], -values[k][0], k)
            )
            require(
                [action_key(row["action"]) for row in cell["ranked"]] == ordered,
                "ranking loses action identity or mean order",
            )
            for row in cell["ranked"]:
                count, total = values[action_key(row["action"])]
                require(
                    row["visits"] == count
                    and isinstance(row["label"], str)
                    and math.isclose(
                        number(row["win_rate"]), total / count, rel_tol=0, abs_tol=1e-14
                    ),
                    "ranked mean does not match raw sums",
                )
        require(len(set(roots.values())) == 3, "declared roots are not distinct")
        pairs = zip(record["cells"][::2], record["cells"][1::2], strict=True)
        require(
            all(computational(cold) == computational(warm) for cold, warm in pairs),
            "cold and warm computational results differ",
        )
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"malformed process study: {exc}") from exc


def ratios(record, workers, phase):
    cells = {
        (c["scenario"], c["search_seed"], c["workers"], c["phase"]): c
        for c in record["cells"]
    }
    return [
        cells[(s, seed, 1, phase)]["elapsed_s"]
        / cells[(s, seed, workers, phase)]["elapsed_s"]
        for s in SCENARIOS
        for seed in SEEDS
    ]


def action_label(row):
    card, target = action_key(row["action"])
    return f"{row['label']} (slot {card}, target {target})"


def blocks(record):
    """Both formats use the same paragraphs and tables from retained values."""
    all_ratios = [
        value
        for phase in PHASES
        for workers in (2, 4)
        for value in ratios(record, workers, phase)
    ]
    faster = sum(value > 1 for value in all_ratios)
    transitions = sorted({c["report"]["transitions"] for c in record["cells"]})
    transition_text = (
        f"{transitions[0]:,}"
        if len(transitions) == 1
        else f"between {min(transitions):,} and {max(transitions):,}"
    )
    all_spent = all(c["report"]["unused_transitions"] == 0 for c in record["cells"])
    summary = []
    for phase in PHASES:
        for workers in (2, 4):
            values = ratios(record, workers, phase)
            summary.append(
                [
                    phase,
                    workers,
                    f"{statistics.median(values):.3f}",
                    f"{min(values):.3f}",
                    f"{max(values):.3f}",
                    len(values),
                ]
            )
    rows, components, allocations = [], [], []
    indexed = {
        (c["scenario"], c["search_seed"], c["workers"], c["phase"]): c
        for c in record["cells"]
    }
    for cell in record["cells"]:
        report = cell["report"]
        base = indexed[(cell["scenario"], cell["search_seed"], 1, cell["phase"])]
        key = [cell["scenario"], cell["search_seed"], cell["workers"], cell["phase"]]
        rows.append(
            key
            + [
                f"{cell['elapsed_s']:.6f}",
                f"{12000 / cell['elapsed_s']:.0f}",
                f"{base['elapsed_s'] / cell['elapsed_s']:.3f}",
                action_label(cell["ranked"][0]),
            ]
        )
        probe = cell["serialization_probe"]
        longest = max(w["elapsed_s"] for w in report["workers"])
        components.append(
            key
            + [
                f"{report['pool_startup_s']:.6f}",
                f"{longest:.6f}",
                f"{cell['elapsed_s'] - longest:.6f}",
                probe["payload_bytes"],
                f"{1000 * probe['encode_s']:.6f}",
                f"{1000 * probe['decode_s']:.6f}",
            ]
        )
        allocations.append(
            key
            + [
                report["simulations"],
                report["transitions"],
                report["unused_simulations"],
                report["unused_transitions"],
            ]
        )
    conditions = record["environment"]["conditions"]
    revision = record["source"]["revision"]
    return [
        (
            "p",
            "I added a fixed total work mode to make parallel search easier to "
            "compare. This first computational study ran 54 searches over three "
            "initial states. Every search completed 12,000 simulations and "
            f"{transition_text} simulator "
            "transitions. The 27 cold and warm pairs returned identical worker seeds, "
            "work counts, raw root statistics and rankings. Only their timings differ.",
        ),
        (
            "p",
            f"The two and four worker runs were faster in {faster} of "
            f"{len(all_ratios)} paired comparisons with one worker. "
            "This is a bounded shared machine result, not a general scaling "
            "guarantee. Each condition was measured once. Ratios above the worker "
            "count "
            "do not establish superlinear scaling because ordinary machine activity "
            "was uncontrolled. No episodes or playing strength comparison ran.",
        ),
        ("h2", "Paired wall time ratios"),
        (
            "p",
            "Each ratio divides the one worker wall time by the matching worker "
            "count's time for the same state, seed and cold or warm condition. Values "
            "above one are faster in this observation. The median, minimum and maximum "
            "describe nine pairs over three states. These are not nine independent "
            "scenario samples, confidence intervals or a significance test.",
        ),
        (
            "table",
            "Paired time ratios",
            [
                "Pool",
                "Workers",
                "Median ratio",
                "Minimum ratio",
                "Maximum ratio",
                "Pairs",
            ],
            summary,
        ),
        ("h2", "What the work contract measures"),
        (
            "p",
            "The protocol uses environment seed 300, search seeds 7, 42 and 99, "
            "a five round horizon and no priors. Each initial state has seven pips "
            "and otherwise keeps its scenario defaults. Worker counts rotate between "
            "seeds. One total allowance is split across independent roots, so two "
            "workers get 6,000 simulations each and four get 3,000 each. Changing the "
            "worker count changes the trees, not just the scheduling of one tree.",
        ),
        (
            "p",
            "Warm means a second search on the same process pool with fresh trees "
            "and the same derived seeds. It does not reuse a search tree. One worker "
            "runs locally without process startup. The multiworker cold condition "
            "includes waiting for every spawned process to announce readiness.",
        ),
        (
            "p",
            "Gauntlet searches selected different targets across configurations. "
            "Those differences are retained below. Mean shaped reward is not a "
            "calibrated win probability, and no outcome here says which selected "
            "action would play better. Slot and target indexes distinguish actions "
            "with the same name. A value of -1 means no slot or target.",
        ),
        ("h2", "Every measured condition"),
        (
            "table",
            "All 54 measured searches",
            [
                "Scenario",
                "Seed",
                "Workers",
                "Pool",
                "Wall seconds",
                "Simulations / second",
                "Time ratio",
                "Selected action",
            ],
            rows,
        ),
        ("h2", "Actual work and stopping"),
        (
            "p",
            "No worker failed, timed out or left unknown work in this attempt. "
            + (
                "All workers stopped at both the simulation cap "
                "and transition allowance. "
                if all_spent
                else "Some workers left unused transition allowance. "
            )
            + "The retained JSON includes every assigned allowance, derived seed, "
            "worker "
            "duration, stopping reason, root visit count and raw value sum. The report "
            "validator reconstructs merged means from those sums and checks all "
            "54 conditions. It does not rerun search or replace an incomplete result.",
        ),
        (
            "table",
            "Work accounting",
            [
                "Scenario",
                "Seed",
                "Workers",
                "Pool",
                "Simulations",
                "Transitions",
                "Unused simulations",
                "Unused transitions",
            ],
            allocations,
        ),
        ("h2", "Startup and transport controls"),
        (
            "p",
            "Startup is the measured process creation and readiness component "
            "inside cold wall time. Longest worker is the largest reported compute "
            "duration. Wall time less that duration is composite orchestration "
            "overhead, including startup when applicable. It is not pure IPC latency. "
            "The payload encode and decode probe runs in the parent before each "
            "search and is excluded from search wall time. Its bytes and timings "
            "describe serialization, not actual transport through a process queue.",
        ),
        (
            "table",
            "Timing components and separate serialization probe",
            [
                "Scenario",
                "Seed",
                "Workers",
                "Pool",
                "Startup seconds",
                "Longest worker seconds",
                "Composite overhead seconds",
                "Payload bytes",
                "Encode ms",
                "Decode ms",
            ],
            components,
        ),
        ("h2", "Environment and evidence"),
        ("p", conditions),
        (
            "p",
            f"Measured source: {revision}. Protocol and implementation were "
            "committed before this first attempt. Source identity stayed unchanged "
            "during measurement. The source hash map and all original timestamps "
            "remain in the retained JSON. This report is a later presentation of "
            "those saved data, not another experiment.",
        ),
        (
            "p",
            f"Python: {record['environment']['python']}. "
            f"Platform: {record['environment']['platform']}. "
            f"Started: {record['started_utc']}. Ended: {record['ended_utc']}.",
        ),
        (
            "p",
            "The root states are public synthetic examples. This study covers "
            "one work allowance, one horizon, three initial states and three seeds "
            "on one machine. It does not measure full game throughput, deployment "
            "latency, cross platform reproducibility or compilation. Earlier "
            "benchmark and baseline studies remain separate and unchanged.",
        ),
    ]


def markdown(record):
    output = [
        "# Fixed work process scaling",
        "",
        "[Interactive report](https://t92t1914.github.io/"
        "mcts-combat-engine/parallel-scaling.html) "
        "| [Raw results](parallel-scaling-results.json) "
        "| [Declared protocol](parallel-scaling-protocol.json) "
        "| [Work contract](parallel-fixed-work.md)",
        "",
    ]
    for block in blocks(record):
        if block[0] == "table":
            _, caption, headers, rows = block
            output += [
                caption,
                "",
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join(["---"] * len(headers)) + " |",
            ]
            output += ["| " + " | ".join(map(str, row)) + " |" for row in rows]
        else:
            output.append(("## " if block[0] == "h2" else "") + block[1])
        output.append("")
    output += [
        "Validate and render the retained result without running the study:",
        "",
        "```sh",
        "python tools/render_parallel_scaling.py --check",
        "```",
        "",
    ]
    return "\n".join(output)


def webpage(record):
    escape = html.escape
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>Fixed work process scaling | MCTS Combat Engine</title>",
        '<script src="appearance.js"></script>'
        '<link rel="stylesheet" href="appearance.css">',
        '<link rel="stylesheet" href="style.css"></head><body>',
        '<a class="skip" href="#main">Skip to the report</a><div class="wrap">',
        '<nav aria-label="Project navigation">'
        '<a href="index.html">Decision explorer</a>',
        '<a href="https://github.com/T92T1914/mcts-combat-engine">'
        "Source on GitHub</a></nav>",
        '<div class="appearance-control"><label for="appearance">Appearance</label>',
        '<select id="appearance" disabled><option value="auto">Auto</option>',
        '<option value="clair">Clair</option>'
        '<option value="obscur">Obscur</option></select>',
        "<noscript>Auto follows your system appearance.</noscript>"
        '</div><main id="main">',
        '<p class="eyebrow">A separate computational study</p>',
        '<h1>Fixed work process scaling</h1><div class="actions">',
        '<a class="button" href="parallel-scaling-results.json" download>'
        "Download raw results</a>",
        '<a class="button" href="parallel-scaling-protocol.json">'
        "Read the declared protocol</a>",
        '<a class="button" href="parallel-scaling-results.md" download>'
        "Download Markdown report</a>",
        "</div>",
    ]
    for block in blocks(record):
        if block[0] == "table":
            _, caption, headers, rows = block
            parts += [
                f'<div class="table-wrap" tabindex="0" role="region" '
                f'aria-label="{escape(caption)}"><table><caption>{escape(caption)}</caption>',
                "<thead><tr>"
                + "".join(f'<th scope="col">{escape(h)}</th>' for h in headers)
                + "</tr></thead><tbody>",
            ]
            parts += [
                "<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in row) + "</tr>"
                for row in rows
            ]
            parts.append("</tbody></table></div>")
        else:
            tag, text = block
            parts.append(f"<{tag}>{escape(text)}</{tag}>")
    parts += [
        "<p>Inter is selected from installed local faces. Other visitors use a system ",
        "fallback. This page makes no font download request. Print uses Clair while ",
        "retaining the saved screen appearance.</p>",
        '<p><a href="presentation.json">Site revision and file provenance</a>. ',
        "The measured source revision above is separate from the site build.</p>",
        "</main><footer>Retained measurements and declared limits. ",
        '<a href="index.html">Return to the decision explorer</a>.'
        "</footer></div></body></html>",
    ]
    return "\n".join(part.rstrip() for part in parts) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    record = json.loads((ROOT / "docs/parallel-scaling-results.json").read_text())
    protocol_path = ROOT / "docs/parallel-scaling-protocol.json"
    try:
        validate(record, json.loads(protocol_path.read_text()), digest(protocol_path))
        for name, text in (
            ("docs/parallel-scaling-results.md", markdown(record)),
            ("site/parallel-scaling.html", webpage(record)),
        ):
            path = ROOT / name
            if args.check:
                require(
                    path.read_text(encoding="utf-8") == text,
                    f"retained report differs: {name}",
                )
            else:
                path.write_text(text, encoding="utf-8", newline="\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Process scaling report: {exc}\n")
    print("All 54 process study cells reconcile. Both report formats match saved data.")


if __name__ == "__main__":
    main()
