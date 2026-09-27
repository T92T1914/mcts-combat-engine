"""Validate and present the retained execution control without running search."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.render_parallel_scaling import (  # noqa: E402
    action_key,
    digest,
    integer,
    number,
    require,
)
from tools.run_same_forest import ORDERS, compare_condition  # noqa: E402

EVALUATED_REVISION = "3adf64e618c277721d7ea36629cc934d0145a3ac"
RESULT_SHA256 = "eba0584f93cc9ca6be21980cf0d48124e00aaf2ab602fa4f2aa1647070e3fba3"
PROTOCOL_SHA256 = "7261776708d2de2cf3fdbb1bb9f3ecae2962e6e5a267c2d7916b6de0166ca32e"
DATA = ROOT / "docs/same-forest-results.json"
PROTOCOL = ROOT / "docs/same-forest-protocol.json"
SOURCES = (
    (
        "Fern and Lewis, Ensemble Monte Carlo Planning",
        "https://eecs.oregonstate.edu/~afern/papers/icaps11_uct.pdf",
        "Sections 3.2, 3.3 and 5 distinguish ensemble size, trajectories per tree "
        "and sequential versus parallel comparisons. Their results do not "
        "establish stronger play or faster execution in this implementation.",
    ),
    (
        "Steinmetz and Gini, author manuscript on parallel search",
        "https://www-users.cse.umn.edu/~gini/publications/papers/Steinmetz2020TG.pdf",
        "Sections II.C, III and V compare independent root trees with other "
        "parallel search arrangements in Go. Separate machines, time allowances "
        "and majority voting differ from this control's fixed total work and "
        "pooled raw statistics.",
    ),
)


def validate_receipt(cell):
    """Reconstruct work and ranking rather than trust a recorded match flag."""
    report = cell["report"]
    roots = cell["roots"]
    require(
        cell["status"] == "completed"
        and cell["error"] is None
        and report["complete"] is True
        and report["seed"] == 42
        and report["max_simulations"] == 12000
        and report["max_transitions"] == 60000,
        "incomplete or changed work contract",
    )
    wall = number(cell["elapsed_s"])
    require(wall > 0, "zero wall time")
    elapsed = number(report["elapsed_s"])
    startup = number(report["pool_startup_s"])
    preparation = number(cell["preparation_s"])
    prepared_startup = number(cell["prepared_pool_startup_s"])
    require(startup <= elapsed <= wall, "search timing exceeds wall time")
    if cell["phase"] == "warm":
        require(
            0 < prepared_startup <= preparation and startup == 0,
            "warm preparation is missing or mixed into search",
        )
    else:
        require(preparation == prepared_startup == 0, "unexpected preparation")
        require(
            startup == 0 if cell["phase"] == "sequential" else startup > 0,
            "unexpected process startup",
        )
    require(len(report["workers"]) == roots, "missing worker")
    merged = {}
    for i, worker in enumerate(report["workers"]):
        sims, cap = 12000 // roots, 60000 // roots
        seed = int.from_bytes(
            hashlib.sha256(f"mcts-root-v1:42:{i}".encode("ascii")).digest()[:8],
            "big",
        )
        require(
            worker["worker_id"] == i
            and worker["seed"] == seed
            and worker["status"] == "completed"
            and worker["error"] is None,
            "worker identity or status differs",
        )
        expected = {
            "assigned_simulations": sims,
            "assigned_transitions": cap,
            "simulations": sims,
            "transitions": cap,
            "unused_simulations": 0,
            "unused_transitions": 0,
            "virtual_visits": 0,
        }
        for key, value in expected.items():
            require(
                type(worker[key]) is int and worker[key] == value,
                f"worker accounting differs: {key}",
            )
        require(
            worker["stop_reasons"] == ["transition_allowance", "simulation_cap"],
            "stopping reasons differ",
        )
        require(number(worker["elapsed_s"]) <= elapsed, "worker exceeds search")
        visits, seen = 0, set()
        for action, count, total in worker["statistics"]:
            key = action_key(action)
            require(key not in seen, "duplicate root action")
            seen.add(key)
            visits += integer(count, 1, sims)
            require(number(total) <= count, "invalid value sum")
            merged.setdefault(key, []).append((count, total))
        require(visits == sims, "visits do not account for work")
    for key, value in {
        "simulations": 12000,
        "known_simulations": 12000,
        "transitions": 60000,
        "known_transitions": 60000,
        "unused_simulations": 0,
        "unused_transitions": 0,
    }.items():
        require(
            type(report[key]) is int and report[key] == value,
            f"aggregate accounting differs: {key}",
        )
    values = {
        key: (sum(n for n, _ in parts), math.fsum(v for _, v in parts))
        for key, parts in merged.items()
    }
    order = sorted(
        values, key=lambda k: (-values[k][1] / values[k][0], -values[k][0], k)
    )
    require(
        [action_key(row["action"]) for row in cell["ranked"]] == order,
        "ranked action identity differs",
    )
    for row in cell["ranked"]:
        count, total = values[action_key(row["action"])]
        require(
            row["visits"] == count
            and isinstance(row["label"], str)
            and number(row["win_rate"]) == total / count,
            "ranked mean differs from raw sums",
        )


def validate(record, protocol):
    """Validate this frozen first attempt and recompute all identity comparisons."""
    try:
        require(
            record["schema_version"] == protocol["schema_version"] == 1,
            "unsupported schema",
        )
        require(
            record["protocol"] == protocol["id"] == "same-forest-execution-v1"
            and record["protocol_sha256"] == PROTOCOL_SHA256,
            "protocol identity differs",
        )
        require(
            record["status"] == "complete"
            and record["source_unchanged_at_end"] is True
            and record["source"]["worktree_clean"] is True,
            "incomplete attempt or unstable source",
        )
        require(
            record["source"]["revision"] == EVALUATED_REVISION,
            "measured revision differs",
        )
        hashes = record["source"]["sha256"]
        require(
            hashes["docs/same-forest-protocol.json"] == PROTOCOL_SHA256
            and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in hashes.values()),
            "source hashes differ",
        )
        expected_conditions = [
            {"scenario": s, "roots": roots, "order": list(order)}
            for (s, roots), order in zip(
                ((s, r) for s in ("duel", "gauntlet", "boss") for r in (2, 4)),
                ORDERS,
                strict=True,
            )
        ]
        require(protocol["conditions"] == expected_conditions, "protocol order differs")
        expected = [
            (c["scenario"], c["roots"], p)
            for c in expected_conditions
            for p in c["order"]
        ]
        require(
            [(c["scenario"], c["roots"], c["phase"]) for c in record["cells"]]
            == expected,
            "missing, duplicate or reordered execution",
        )
        env = record["environment"]
        require(
            env["start_method"] == "spawn"
            and env["python"]
            and env["platform"]
            and env["conditions"],
            "missing environment",
        )
        roots = {}
        for cell in record["cells"]:
            require(
                cell["search_seed"] == 42 and cell["environment_seed"] == 300,
                "changed seeds",
            )
            root_hash = cell["root_pickle_sha256"]
            require(
                re.fullmatch(r"[0-9a-f]{64}", root_hash)
                and roots.setdefault(cell["scenario"], root_hash) == root_hash,
                "root identity differs",
            )
            validate_receipt(cell)
        require(len(set(roots.values())) == 3, "scenario roots are not distinct")
        comparisons = [
            compare_condition(record["cells"][i : i + 3]) for i in range(0, 18, 3)
        ]
        require(all(c["matched"] for c in comparisons), "forest mismatch")
        require(record["comparisons"] == comparisons, "saved comparisons differ")
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"malformed execution control: {exc}") from exc


def blocks(record):
    summary, preparation, work = [], [], []
    for comparison in record["comparisons"]:
        cells = {
            c["phase"]: c
            for c in record["cells"]
            if (c["scenario"], c["roots"])
            == (comparison["scenario"], comparison["roots"])
        }
        summary.append(
            [comparison["scenario"], comparison["roots"]]
            + [f"{cells[p]['elapsed_s']:.6f}" for p in ("sequential", "cold", "warm")]
            + [
                f"{comparison['sequential_wall_ratio'][p]:.3f}"
                for p in ("cold", "warm")
            ]
        )
    for c in record["cells"]:
        key = [c["scenario"], c["roots"], c["phase"]]
        preparation.append(
            key
            + [
                f"{c['preparation_s']:.6f}",
                f"{c['prepared_pool_startup_s']:.6f}",
                f"{c['report']['pool_startup_s']:.6f}",
                f"{max(w['elapsed_s'] for w in c['report']['workers']):.6f}",
            ]
        )
        work.append(
            key
            + [
                c["report"][field]
                for field in (
                    "simulations",
                    "transitions",
                    "unused_simulations",
                    "unused_transitions",
                )
            ]
        )
    boss = {
        c["phase"]: c
        for c in record["cells"]
        if c["scenario"] == "boss" and c["roots"] == 2
    }
    return [
        (
            "p",
            "All 18 executions completed. In each of the six conditions, "
            "sequential execution and both process modes returned exactly the same "
            "worker seeds, work accounting, stopping reasons, raw root statistics and "
            "ranked actions. Each execution spent 12,000 simulations and 60,000 "
            "simulator transitions, with no unused allowance.",
        ),
        (
            "p",
            "This control holds the forest fixed while changing how its roots "
            "execute. It separates execution timing from the change in search "
            "structure "
            "caused by dividing work among a different number of trees. Two roots and "
            "four roots remain different forests. This is not a playing strength "
            "study.",
        ),
        ("h2", "Timing of identical forests"),
        (
            "p",
            "On narrow screens, scroll each table sideways for the remaining "
            "columns. Tab to a table and use the arrow keys when browsing by "
            "keyboard.",
        ),
        (
            "p",
            "Each row is one condition with one observation per execution mode. "
            "A ratio divides sequential wall time by process wall time for that same "
            "forest. Ratios above one mean the process execution was faster in this "
            "observation. They are not confidence intervals or a general scaling "
            "claim. "
            "Some warm ratios exceed the root count. Uncontrolled ordinary machine "
            "activity and one observation cannot establish superlinear scaling.",
        ),
        (
            "table",
            "Observed wall seconds and ratios",
            [
                "Scenario",
                "Roots",
                "Sequential s",
                "Cold s",
                "Warm s",
                "Sequential / cold",
                "Sequential / warm",
            ],
            summary,
        ),
        (
            "p",
            f"With two Boss roots, warm execution took {boss['warm']['elapsed_s']:.6f} "
            f"seconds while cold execution took {boss['cold']['elapsed_s']:.6f} "
            "seconds. "
            "That slower warm observation is retained. The control does not explain "
            "its cause or justify assuming warm execution is always faster.",
        ),
        ("h2", "What warm includes"),
        (
            "p",
            "Sequential and cold wall time include engine construction and the "
            "search call. Warm initializes a fresh engine and process pool before "
            "starting the search timer. No unrecorded search warms that pool. This "
            "differs from the earlier process study, where warm meant a second search "
            "on a reused pool. Every execution here builds fresh trees. Cleanup occurs "
            "outside the search timer.",
        ),
        (
            "p",
            "Warm preparation and its contained pool startup are listed separately. "
            "Do not add both values as independent costs. Cold startup is already "
            "inside cold wall time. Longest root reports a component of computation, "
            "not an additional cost. These observations include scheduling and "
            "orchestration effects and do not isolate pure IPC latency.",
        ),
        (
            "table",
            "Preparation and timing components in seconds",
            [
                "Scenario",
                "Roots",
                "Mode",
                "Preparation s",
                "Prepared startup s",
                "Startup in search s",
                "Longest root s",
            ],
            preparation,
        ),
        ("h2", "Identity and work accounting"),
        (
            "p",
            "The same WorkerJob allocation, seed derivation, fixed search, receipt "
            "validation and raw statistic merge serve every mode. Sequential execution "
            "uses the configured number of independent roots locally. It does not "
            "substitute one larger tree. Root seeds derive from search seed 42 and "
            "stable worker IDs. Raw visits and value sums merge in worker ID order.",
        ),
        (
            "p",
            "All six comparisons match after removing only report and worker "
            "durations and pool startup. Every worker stopped at both the simulation "
            "cap and transition allowance. No execution failed or left unknown work. "
            "The retained JSON contains all receipts, action identities and means. "
            "Its compatibility field win_rate is mean shaped reward, not a calibrated "
            "win probability. The report validator reconstructs that mean from "
            "raw sums.",
        ),
        (
            "table",
            "All 18 execution receipts",
            [
                "Scenario",
                "Roots",
                "Mode",
                "Simulations",
                "Transitions",
                "Unused simulations",
                "Unused transitions",
            ],
            work,
        ),
        ("h2", "Protocol, chronology and limits"),
        (
            "p",
            "This follow up was designed after the completed 54 cell process study. "
            "The literature review below informed this new execution control, not that "
            "earlier protocol. Its six execution orders were fixed before measurement, "
            "with each mode twice in each ordinal position. It uses environment seed "
            "300, search seed 42, horizon five and no priors. Each ordinary scenario "
            "starts with seven player pips and otherwise retains its defaults.",
        ),
        (
            "p",
            f"Measured source: {record['source']['revision']}. Implementation and "
            "protocol were committed and reviewed before this first attempt. Source "
            "identity remained unchanged during collection. The report and website "
            "are later presentations of retained measurements, not new experiments.",
        ),
        ("p", record["environment"]["conditions"]),
        (
            "p",
            f"Python: {record['environment']['python']}. Platform: "
            f"{record['environment']['platform']}. Started: {record['started_utc']}. "
            f"Ended: {record['ended_utc']}.",
        ),
        (
            "p",
            "One search seed, three initial states, two forest sizes and one "
            "observation per mode on one machine do not establish general speedup, "
            "cross platform performance or statistical significance. No episodes, "
            "quality comparison or parameter tuning followed the outcomes. Earlier "
            "studies and their unfavorable results remain unchanged.",
        ),
    ]


def markdown(record):
    output = [
        "# Same forest, different execution",
        "",
        "[Interactive report](https://t92t1914.github.io/mcts-combat-engine/"
        "same-forest.html) | [Raw results](same-forest-results.json) | "
        "[Declared protocol](same-forest-protocol.json) | "
        "[Earlier process study](parallel-scaling-results.md)",
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
    output += ["## Subsequent method context", ""]
    for title, url, note in SOURCES:
        output += [f"[{title}]({url}). {note}", ""]
    output += [
        "Validate and render these retained data without executing a search:",
        "",
        "```sh",
        "python tools/render_same_forest.py --check",
        "```",
        "",
    ]
    return "\n".join(output)


def webpage(record):
    esc = html.escape
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>Same forest execution | MCTS Combat Engine</title>",
        '<script src="appearance.js"></script>',
        '<link rel="stylesheet" href="appearance.css">',
        '<link rel="stylesheet" href="style.css"></head>'
        '<body class="execution-report">',
        '<a class="skip" href="#main">Skip to the report</a><div class="wrap">',
        '<nav aria-label="Project navigation"><a href="index.html">'
        'Decision explorer</a>',
        '<a href="parallel-scaling.html">Earlier process study</a></nav>',
        '<div class="appearance-control"><label for="appearance">Appearance</label>',
        '<select id="appearance" disabled><option value="auto">Auto</option>',
        '<option value="clair">Clair</option><option value="obscur">Obscur</option>',
        "</select><noscript>Auto follows your system appearance.</noscript></div>",
        '<main id="main"><p class="eyebrow">A separate execution control</p>',
        '<h1>Same forest, different execution</h1><div class="actions">',
        '<a class="button" href="same-forest-results.json" download>'
        'Download raw results</a>',
        '<a class="button" href="same-forest-protocol.json">'
        'Read the declared protocol</a>',
        '<a class="button" href="same-forest-results.md" download>',
        "Download Markdown report</a></div>",
    ]
    for block in blocks(record):
        if block[0] == "table":
            _, caption, headers, rows = block
            parts += [
                f'<div class="table-wrap" tabindex="0" role="region" '
                f'aria-label="{esc(caption)}"><table><caption>{esc(caption)}</caption>',
                "<thead><tr>"
                + "".join(f'<th scope="col">{esc(h)}</th>' for h in headers)
                + "</tr></thead><tbody>",
            ]
            parts += [
                "<tr>" + "".join(f"<td>{esc(str(v))}</td>" for v in row) + "</tr>"
                for row in rows
            ]
            parts.append("</tbody></table></div>")
        else:
            tag, text = block
            parts.append(f"<{tag}>{esc(text)}</{tag}>")
    parts.append("<h2>Subsequent method context</h2>")
    for title, url, note in SOURCES:
        parts.append(f'<p><a href="{esc(url)}">{esc(title)}</a>. {esc(note)}</p>')
    parts += [
        "<p>Inter uses installed local faces, with a system fallback for other ",
        "visitors and no remote font request. Print uses Clair without changing ",
        'the saved screen appearance.</p><p><a href="presentation.json">',
        "Site revision and file provenance</a>. The evaluated source above is ",
        "separate from the site build.</p></main><footer>Retained measurements ",
        'and declared limits. <a href="index.html">Return to the decision explorer',
        "</a>.</footer></div></body></html>",
    ]
    return "\n".join(part.rstrip() for part in parts) + "\n"


def check_outputs(write=False):
    require(
        hashlib.sha256(DATA.read_bytes()).hexdigest() == RESULT_SHA256,
        "retained first attempt bytes changed",
    )
    require(digest(PROTOCOL) == PROTOCOL_SHA256, "declared protocol changed")
    record = json.loads(DATA.read_text(encoding="utf-8"))
    validate(record, json.loads(PROTOCOL.read_text(encoding="utf-8")))
    for name, text in (
        ("docs/same-forest-results.md", markdown(record)),
        ("site/same-forest.html", webpage(record)),
    ):
        path = ROOT / name
        if write:
            path.write_text(text, encoding="utf-8", newline="\n")
        else:
            require(
                path.read_text(encoding="utf-8") == text,
                f"retained report differs: {name}",
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        check_outputs(write=not args.check)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Same forest report: {exc}\n")
    print("18 retained executions reconcile. Six identical forest comparisons match.")


if __name__ == "__main__":
    main()
