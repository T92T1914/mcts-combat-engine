"""Validate repeated same-work receipts and summarize process-block uncertainty."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.derive_same_forest_public_receipts import FIELDS  # noqa: E402
from tools.render_parallel_scaling import computational, number, require  # noqa: E402
from tools.render_same_forest import validate_receipt  # noqa: E402
from tools.run_parallel_scaling import digest  # noqa: E402
from tools.run_same_forest import compare_condition, differing_paths  # noqa: E402
from tools.run_same_forest_repeatability import (  # noqa: E402
    CONDITIONS,
    PROTOCOL,
    schedule,
    validate_protocol,
)

DATA = ROOT / "docs/same-forest-repeatability-public-receipts.json"
REPORT = ROOT / "docs/same-forest-repeatability-results.md"
FAILED = ROOT / "docs/same-forest-repeatability-public-failed-attempt.json"
PROVENANCE = ROOT / "docs/same-forest-repeatability-provenance.json"
PUBLIC_FIELDS = ROOT / "docs/same-forest-repeatability-public-fields.json"
PAGE = ROOT / "site/same-forest-repeatability.html"
RESULT_SHA256 = "4dfd39199cf55e61a53f527f055c562cdc4fc37598c80103749111786b8358e9"
FAILED_SHA256 = "3a9124175b9f25b8ef78bcceb154e87c9fbf823e873ec18f5f0127f76bc74014"
PRIVATE_COMPLETE = {
    "bytes": 2898540,
    "sha256": "552342df0e7800d85a2b092f0a33f03d147323b91081e5e56d9f594329bb4160",
}
PRIVATE_FAILED = {
    "bytes": 19193,
    "sha256": "807583e64f0affd853ae4c34651e9250122aca24696edb28715613c656c74ffd",
}
MEASURED_REVISION = "60bd4848427b2489e7bec4048170407b0c8f4e99"
MEASURED_TREE = "a65a176e3640c5ec8991a40231e5c550fc66a97a"
PUBLIC_MEASUREMENT_REVISION = "fb7addac28a6045fcb8f6cbaedc31c4808b4058a"
T_CRITICAL = 2.571  # NIST table, two-sided 95 percent, five degrees of freedom.


def nested_record_encoding(block, declared_sha256):
    """Match the exact retained serializer bytes, allowing native LF or CRLF."""
    encoded = (json.dumps(block, indent=2, allow_nan=False) + "\n").encode("utf-8")
    for newline, candidate in (
        ("LF", encoded),
        ("CRLF", encoded.replace(b"\n", b"\r\n")),
    ):
        observed = hashlib.sha256(candidate).hexdigest()
        if observed == declared_sha256:
            return {"newline": newline, "bytes": len(candidate), "sha256": observed}
    raise ValueError("nested record bytes differ")


def validate(record, protocol, public_derivative=False):
    """Reject partial groups, bad matching work and flattened repetition claims."""
    validate_protocol(protocol)
    try:
        require(record["schema_version"] == 1, "unsupported result schema")
        require(
            record["protocol"] == protocol["id"]
            and record["protocol_sha256"] == digest(PROTOCOL),
            "protocol mismatch",
        )
        require(
            record["status"] == "complete"
            and record["source_unchanged_at_end"] is True,
            "incomplete attempt",
        )
        source = record["source"]
        require(
            source["worktree_clean"] is True
            and re.fullmatch(r"[0-9a-f]{40}", source["revision"]),
            "invalid source",
        )
        require(
            source["sha256"]["docs/same-forest-repeatability-protocol.json"]
            == record["protocol_sha256"],
            "source protocol mismatch",
        )
        require(
            all(
                re.fullmatch(r"[0-9a-f]{64}", value)
                for value in source["sha256"].values()
            ),
            "invalid source hashes",
        )
        require(
            source["retained_first_attempt_sha256"]
            == "eba0584f93cc9ca6be21980cf0d48124e00aaf2ab602fa4f2aa1647070e3fba3",
            "original observation changed",
        )
        env = record["environment"]
        if public_derivative:
            validate_public_metadata(record, PRIVATE_COMPLETE)
        else:
            require(
                env["python"]
                and env["platform"]
                and env["conditions"]
                and env["start_method"] == "spawn"
                and re.fullmatch(r"[0-9a-f]{64}", env["interpreter_sha256"]),
                "missing environment",
            )
        require(record["process_tree_bound"], "missing external resource control")
        require(
            0 < number(record["collection_wall_s"]) <= 300,
            "collection exceeds declared maximum cost",
        )
        require(len(record["blocks"]) == 6, "six fresh blocks required")
        roots, identities = {}, {}
        for block_index, item in enumerate(record["blocks"]):
            require(
                type(item["block"]) is int
                and item["block"] == block_index
                and item["returncode"] == 0
                and item["status"] == "complete",
                "incomplete or reordered controller",
            )
            require(number(item["controller_wall_s"]) > 0, "invalid controller time")
            block = item["record"]
            nested_record_encoding(block, item["record_sha256"])
            require(
                block["source"] == source
                and block["status"] == "complete"
                and block["source_unchanged_at_end"] is True
                and block["block"] == block_index
                and block["protocol"] == record["protocol"]
                and block["protocol_sha256"] == record["protocol_sha256"],
                "block source or control differs",
            )
            expected = schedule(block_index)
            require(block["schedule"] == expected, "declared schedule differs")
            keys = [
                (block_index, c["iteration"], c["scenario"], c["roots"], phase)
                for c in expected
                for phase in c["order"]
            ]
            actual = [
                (c["block"], c["iteration"], c["scenario"], c["roots"], c["phase"])
                for c in block["cells"]
            ]
            require(
                not differing_paths(actual, keys),
                "missing, duplicated or reordered execution",
            )
            comparisons = []
            for index, cell in enumerate(block["cells"]):
                require(
                    cell["search_seed"] == 42 and cell["environment_seed"] == 300,
                    "changed search inputs",
                )
                validate_receipt(cell)
                complete = number(cell["complete_call_s"])
                require(
                    complete >= cell["elapsed_s"] + cell["preparation_s"],
                    "complete call excludes preparation or search",
                )
                key = cell["scenario"]
                root = cell["root_pickle_sha256"]
                require(
                    re.fullmatch(r"[0-9a-f]{64}", root)
                    and roots.setdefault(key, root) == root,
                    "root identity differs",
                )
                key = (cell["scenario"], cell["roots"])
                identity = computational(cell)
                require(
                    not differing_paths(identities.setdefault(key, identity), identity),
                    "forest differs between blocks",
                )
                if index % 3 == 2:
                    comparison = compare_condition(
                        block["cells"][index - 2 : index + 1]
                    )
                    comparison.update(block=block_index, iteration=cell["iteration"])
                    require(comparison["matched"], "forest mismatch")
                    comparisons.append(comparison)
            require(block["comparisons"] == comparisons, "saved comparisons differ")
            require(
                item["controller_wall_s"]
                >= sum(c["complete_call_s"] for c in block["cells"]),
                "controller interval excludes complete calls",
            )
        require(len(set(roots.values())) == 3, "scenario roots are not distinct")
        require(
            record["collection_wall_s"]
            >= sum(item["controller_wall_s"] for item in record["blocks"]),
            "collection interval excludes controller invocations",
        )
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"malformed repeatability record: {exc}") from exc


def summarize(record):
    """Each mean has six outer units, not 12 independent observations."""
    rows = []
    for scenario, roots in CONDITIONS:
        for metric in ("elapsed_s", "complete_call_s"):
            for phase in ("cold", "warm"):
                nested = []
                for item in record["blocks"]:
                    pairs = []
                    for iteration in range(2):
                        cells = {
                            c["phase"]: c
                            for c in item["record"]["cells"]
                            if (c["scenario"], c["roots"], c["iteration"])
                            == (scenario, roots, iteration)
                        }
                        pairs.append(
                            math.log(cells["sequential"][metric] / cells[phase][metric])
                        )
                    nested.append(pairs)
                means = [statistics.fmean(values) for values in nested]
                mean = statistics.fmean(means)
                variance = statistics.variance(means)
                within = statistics.fmean(statistics.variance(v) for v in nested)
                half_width = T_CRITICAL * math.sqrt(variance / 6)
                low, high = math.exp(mean - half_width), math.exp(mean + half_width)
                rows.append(
                    {
                        "scenario": scenario,
                        "roots": roots,
                        "metric": metric,
                        "phase": phase,
                        "sampling_units": 6,
                        "iterations_per_unit": 2,
                        "degrees_of_freedom": 5,
                        "geometric_mean_ratio": math.exp(mean),
                        "approximate_95_interval": [low, high],
                        "block_log_ratio_means": means,
                        "nested_log_ratios": nested,
                        "sample_variance_of_block_means": variance,
                        "mean_within_block_sample_variance": within,
                        "method_of_moments_between_block_variance": max(
                            0.0, variance - within / 2
                        ),
                        "result": "bounded advantage"
                        if low > 1
                        else "bounded disadvantage"
                        if high < 1
                        else "inconclusive",
                    }
                )
    return rows


def markdown(record, summary, provenance=None):
    lines = [
        "# Repeated same-forest execution",
        "",
        "[Public receipt derivative](same-forest-repeatability-public-receipts.json) | "
        "[Predeclared protocol](same-forest-repeatability-protocol.json) | "
        "[Original one-observation control](same-forest-results.md)",
        "",
        "All 216 executions completed and matched the same computational "
        "receipts within every condition across six fresh Python controller "
        "processes. Each controller ran two repetitions per condition. "
        "Each execution retained 12,000 simulations and 60,000 transitions. "
        "The search algorithm and seeds did not change.",
        "",
        "The table estimates a geometric mean of paired sequential/process "
        "wall-time ratios. Above 1 favors processes. Each approximate "
        "95-percent interval uses six process-block means, df 5 and the "
        "predeclared rounded Student-t critical value 2.571. The two inner "
        "repetitions are not counted as independent processes. These are "
        "individual intervals, not simultaneous confidence across all 24 "
        "comparisons.",
        "",
        "| Scenario | Roots | Timer | Process | Ratio | "
        "Approximate 95% interval | Decision |",
        "| --- | ---: | --- | --- | ---: | --- | --- |",
    ]
    for row in summary:
        low, high = row["approximate_95_interval"]
        lines.append(
            f"| {row['scenario']} | {row['roots']} | {row['metric']} | "
            f"{row['phase']} | {row['geometric_mean_ratio']:.3f} | "
            f"{low:.3f} to {high:.3f} | {row['result']} |"
        )
    lines += [
        "",
        "## Timing and sampling limits",
        "",
        "The original search timer includes engine construction in sequential "
        "and cold calls but excludes warm pool preparation. The new complete "
        "call includes preparation, the search, receipt conversion, the "
        "root-mutation check and owned pool cleanup. Controller invocation "
        "cost is retained separately and is not apportioned among modes. "
        "Overlapping components must not be added.",
        "",
        "Fresh controllers share one machine and one interpreter installation. "
        "No rebuild or cross-machine level was sampled. The approximate "
        "interval assumes reasonably independent, approximately normal block "
        "means. Shared activity, drift and six blocks limit that assumption. "
        "Within the complete attempt, no search was discarded as warmup "
        "and no failed block was retried. "
        "There was no outcome-based early stopping or tuning. The maximum-cost "
        "rule was 300 seconds with a 70-second admission reserve.",
        "",
        "Three fixed initial states and one seed do not represent all workloads "
        "or general search quality. Repetition cannot establish stronger play, "
        "superlinear scaling or portability. Original unfavorable observations "
        "remain in the earlier report.",
        "",
        f"Measured revision: `{record['source']['revision']}`. Collection wall "
        f"time: {record['collection_wall_s']:.3f} seconds. "
        f"Started: {record['started_utc']}. Ended: {record['ended_utc']}.",
        "",
        record["environment"]["conditions"],
        "",
        "## Method sources and reproduction",
        "",
        "[Kalibera and Jones, Rigorous Benchmarking in Reasonable Time]"
        "(https://kar.kent.ac.uk/33611/) supplied the distinction between "
        "repetition levels through its fetched abstract, author page and "
        "repository abstract. The corrected full manuscript timed out. This "
        "supplement does not claim to implement its complete cost or Fieller "
        "model.",
        "",
        "[NIST confidence limits for a mean]"
        "(https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm) and "
        "[Student-t critical values]"
        "(https://www.itl.nist.gov/div898/handbook/eda/section3/eda3672.htm) "
        "define the declared ordinary mean interval on the process-block "
        "log ratios and the rounded df 5 value.",
        "",
        "Validate this report without running search:",
        "",
        "```sh",
        "python tools/render_same_forest_repeatability.py --check",
        "```",
        "",
    ]
    if provenance is not None:
        failed = provenance["failed_attempt"]
        analysis = provenance["analysis"]
        complete = provenance["complete_attempt"]
        snapshot = provenance["measurement_source_snapshot"]
        lines += [
            "## Measured source snapshot",
            "",
            f"The collection used recorded local revision `{MEASURED_REVISION}`. "
            "Its complete Git tree matches the "
            "[public measurement source snapshot]"
            "(https://github.com/T92T1914/mcts-combat-engine/tree/"
            f"{snapshot['public_equivalent_revision']}). Both trees are "
            f"`{snapshot['recorded_git_tree']}`, with identical paths, modes "
            "and blobs. The public commit has different commit metadata and "
            "history. This is source-tree equivalence, not preservation of "
            "the original commit identity.",
            "",
            "No receipt revision, timer or measured value was rewritten for "
            "publication. A new collection from the public snapshot would "
            "record its public commit identity and produce a separate attempt. "
            "Use the current public checkout for the retained-data validation "
            "command above. The local analysis correction recorded below is "
            "historical. The current report generator also includes later "
            "presentation and privacy work and is not the measured source.",
            "",
            "## Retained attempts and analysis",
            "",
            "[Attempt provenance](same-forest-repeatability-provenance.json) | "
            "[First failed attempt derivative]"
            "(same-forest-repeatability-public-failed-attempt.json)",
            "",
            f"The first collection at `{failed['measured_revision']}` "
            "failed after one completed cell. An in-memory dataclass tuple "
            "was passed to a validator for retained JSON arrays. The saved "
            "first cell validates as JSON. This failed collection is retained "
            "and supplies no timing evidence.",
            "",
            "After the producer correction was independently reviewed, a "
            "new whole attempt used the same frozen protocol and resource "
            "bounds. No partial block was reused and no outcome-based "
            "budget or order change was made.",
            "",
            "The complete attempt's first analysis stopped at the nested "
            "raw-byte hash gate before producing a timing summary. All six "
            "saved blocks matched their declared hashes and the native "
            "Windows CRLF serializer. The analyzer correction accepts only "
            "exact canonical LF or CRLF forms. Changed values, arbitrary "
            "formatting and invalid stopping receipts remain rejected. "
            "Search was not rerun for this correction.",
            "",
            f"Validated analysis revision: `{analysis['validated_revision']}`. "
            "The measured source hashes were checked against committed "
            "measured-revision blobs. The current non-analyzer inputs also "
            "matched retained pins. Subsequent report and figure rendering "
            "does not change the measured revision.",
            "",
            f"Outer job wall time: {complete['outer_job_wall_s']:.3f} seconds. "
            f"Full call wall time: {complete['full_call_wall_s']:.3f} seconds. "
            "The controller observed zero active owned processes at "
            "retirement, stable input pins and a passed post-write resource "
            "gate. The retained provenance records the limits separately "
            "from the search and complete-call timers.",
            "",
            "## Public derivative boundary",
            "",
            "[Field-removal manifest](same-forest-repeatability-public-fields.json)",
            "",
            "The downloads are public receipt derivatives, not the exact original "
            "raw files. They omit operating-system process IDs, the exact OS build, "
            "the Python compiler/build string and the interpreter binary hash. "
            "Python 3.11.8, Windows, spawn and 16 logical CPUs remain as resource "
            "context. Every computational receipt, timer, declared control and "
            "schedule is unchanged. Public block hashes identify derived LF "
            "records. The original private SHA256 and byte lengths are retained "
            "in provenance. Public data alone cannot verify withheld original "
            "bytes or environment fingerprints.",
            "",
            "## Figures from the retained data",
            "",
            "[Search interval, Clair](same-forest-repeatability-search-clair.svg) | "
            "[Search interval, Obscur](same-forest-repeatability-search-obscur.svg)",
            "",
            "[Complete call, Clair](same-forest-repeatability-complete-clair.svg) | "
            "[Complete call, Obscur](same-forest-repeatability-complete-obscur.svg)",
            "",
            "The points show geometric means and the horizontal bars "
            "show the individual approximate 95-percent intervals from the "
            "table. Both appearances use the same values and axis. The "
            "search timer excludes warm preparation. Complete call includes "
            "preparation and cleanup. Tables remain the selectable, "
            "nonvisual route to every plotted value.",
            "",
        ]
    return "\n".join(lines)


def validate_provenance(provenance, record, failed):
    """Bind publication to the exact two retained attempts, not mutable timing data."""
    require(provenance["schema_version"] == 1, "unsupported provenance")
    require(
        provenance.get("measurement_source_snapshot")
        == {
            "recorded_local_revision": MEASURED_REVISION,
            "recorded_git_tree": MEASURED_TREE,
            "public_equivalent_revision": PUBLIC_MEASUREMENT_REVISION,
            "public_git_tree": MEASURED_TREE,
            "equivalence": "Complete Git tree with identical paths, modes and blobs",
            "original_commit_identity_preserved": False,
            "retained_receipt_revisions_rewritten": False,
            "search_rerun_for_publication": False,
        },
        "measurement source snapshot mapping differs",
    )
    for key, path, sha256, length, status, revision in (
        (
            "complete_attempt",
            DATA,
            RESULT_SHA256,
            2810474,
            "complete",
            MEASURED_REVISION,
        ),
        (
            "failed_attempt",
            FAILED,
            FAILED_SHA256,
            19423,
            "incomplete",
            "600b962a69d5e46cfccdd0898a21b8e6750cd6e8",
        ),
    ):
        item = provenance[key]
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == sha256
            and path.stat().st_size == length,
            "retained attempt bytes changed",
        )
        require(
            item["sha256"] == sha256
            and item["bytes"] == length
            and item["measured_revision"] == revision
            and item["status"] == status,
            "provenance attempt identity differs",
        )
        require(item["file"] == path.name, "public receipt filename differs")
        require(
            item["owned_processes_after_retirement"] == 0
            and item["end_input_pins_unchanged"] is True,
            "unretired or changed inputs",
        )
    require(
        record["source"]["revision"] == MEASURED_REVISION
        and failed["source"]["revision"]
        == provenance["failed_attempt"]["measured_revision"]
        and failed["status"] == "incomplete",
        "measured source differs",
    )
    require(
        sum(len(b["record"]["cells"]) for b in failed["blocks"]) == 1
        and failed["blocks"][0]["record"]["status"] == "interrupted",
        "failed attempt scope differs",
    )
    validate_receipt(failed["blocks"][0]["record"]["cells"][0])
    validate_public_metadata(failed, PRIVATE_FAILED)
    require(
        provenance["complete_attempt"]["private_original_identity"] == PRIVATE_COMPLETE
        and provenance["failed_attempt"]["private_original_identity"] == PRIVATE_FAILED,
        "private original provenance differs",
    )
    correction = provenance["corrected_collection"]
    require(
        correction["new_whole_attempt"] is True
        and correction["partial_blocks_reused"] is False
        and correction["protocol_controls_changed"] is False
        and correction["budget_changed"] is False
        and correction["outcome_based_tuning"] is False
        and provenance["failed_attempt"]["performance_evidence"] is False,
        "attempt disposition differs",
    )
    analysis = provenance["analysis"]
    require(
        analysis["validated_revision"] == "11e01adebd09046d7853c057f75183d4ce4b1675"
        and analysis["search_rerun_for_analysis"] is False
        and analysis["all_216_receipts_validated"] is True
        and analysis["six_retained_block_byte_hashes_validated"] is True,
        "analysis disposition differs",
    )
    complete = provenance["complete_attempt"]
    require(
        complete["collection_wall_s"] == record["collection_wall_s"]
        and complete["controller_exit_code"] == 0
        and provenance["failed_attempt"]["controller_exit_code"] == 1
        and complete["post_write_resource_gate_passed"] is True
        and complete["collection_wall_s"]
        <= complete["outer_job_wall_s"]
        <= complete["full_call_wall_s"]
        <= 330,
        "outer collection bounds differ",
    )
    bounds = provenance["resource_bounds"]
    require(
        bounds
        == {
            "collection_wall_s": 300,
            "full_call_wall_s": 330,
            "job_committed_memory_bytes": 1073741824,
            "maximum_search_workers": 4,
            "whole_job_priority": "below-normal",
            "owned_job_kill_on_close": True,
            "foreground_used": False,
            "user_applications_or_settings_changed": False,
        },
        "resource scope differs",
    )


def inline(text):
    """Escape the bounded generated report while retaining authored source links."""
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)

    def link(match):
        label, url = match.groups()
        if not (url.startswith("https://") or re.fullmatch(r"[a-z0-9.-]+", url)):
            return match.group(0)
        return f'<a href="{url}">{label}</a>'

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, escaped)


def validate_public_metadata(record, private_identity):
    expected = {
        "format": "same-forest-public-receipts-v1",
        "original_private_identity": private_identity,
        "changed_fields": FIELDS,
        "nested_hashes": "Public derivative canonical LF bytes, "
        "not original raw blocks",
        "computational_receipts_timers_controls_schedules_changed": False,
    }
    require(record["publication_derivative"] == expected, "public derivative differs")
    environment = record["environment"]
    require(
        set(environment)
        == {"python", "platform", "logical_cpus", "start_method", "conditions"}
        and environment["python"] == "3.11.8"
        and environment["platform"] == "Windows"
        and environment["logical_cpus"] == 16
        and environment["start_method"] == "spawn"
        and environment["conditions"],
        "public environment differs",
    )
    for item in record["blocks"]:
        require(
            "pid" not in item["record"]
            and item["record_hash_kind"] == "public derivative canonical LF bytes",
            "public block metadata differs",
        )


def webpage(record, summary, provenance):
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>Repeated same-forest execution | MCTS Combat Engine</title>",
        '<script src="appearance.js"></script>',
        '<link rel="stylesheet" href="appearance.css">',
        '<link rel="stylesheet" href="style.css"></head>',
        '<body class="execution-report"><a class="skip" href="#main">',
        'Skip to the report</a><div class="wrap">',
        '<nav aria-label="Project navigation"><a href="index.html">',
        'Decision explorer</a><a href="same-forest.html">Original control</a></nav>',
        '<div class="appearance-control"><label for="appearance">Appearance</label>',
        '<select id="appearance" disabled><option value="auto">Auto</option>',
        '<option value="clair">Clair</option><option value="obscur">Obscur</option>',
        "</select><noscript>Auto follows your system appearance.</noscript></div>",
        '<main id="main"><p class="eyebrow">A bounded repetition supplement</p>',
        '<div class="actions"><a class="button" download ',
        'href="same-forest-repeatability-public-receipts.json">'
        "Download public receipts</a>",
        '<a class="button" download href="same-forest-repeatability-results.md">',
        "Download Markdown report</a></div>",
    ]
    table, code = False, False
    for line in markdown(record, summary, provenance).splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if not table:
                parts += [
                    "<p>Tab to the table and use arrow keys to scroll. ",
                    "Every figure value is also available here.</p>",
                    '<div class="table-wrap" tabindex="0" role="region" ',
                    'aria-label="Paired ratios and individual intervals"><table>',
                    "<caption>Paired ratios and individual intervals</caption>",
                    "<thead><tr>"
                    + "".join('<th scope="col">' + inline(c) + "</th>" for c in cells)
                    + "</tr></thead><tbody>",
                ]
                table = True
            elif not all(re.fullmatch(r"[-: ]+", c) for c in cells):
                parts.append(
                    "<tr>"
                    + "".join("<td>" + inline(c) + "</td>" for c in cells)
                    + "</tr>"
                )
            continue
        if table:
            parts.append("</tbody></table></div>")
            table = False
        if line.startswith("```"):
            parts.append("</code></pre>" if code else '<pre tabindex="0"><code>')
            code = not code
        elif code:
            parts.append(html.escape(line))
        elif line.startswith("# "):
            parts.append("<h1>" + inline(line[2:]) + "</h1>")
        elif line.startswith("## "):
            parts.append("<h2>" + inline(line[3:]) + "</h2>")
        elif line:
            parts.append("<p>" + inline(line) + "</p>")
    parts.append('<div class="two">')
    for metric, title in (("complete", "Complete call"), ("search", "Search interval")):
        parts.append("<figure>")
        for mode in ("clair", "obscur"):
            parts.append(
                f'<div class="decision-{mode}"><img width="1000" '
                f'height="1160" loading="lazy" '
                f'src="same-forest-repeatability-{metric}-{mode}.png" '
                f'alt="{title}. Cold circles and warm squares show six '
                "paired condition ratios with individual approximate "
                '95-percent intervals. All values are in the table above."></div>'
            )
        parts.append(
            f"<figcaption>{title}. Sequential / process wall time. "
            "Above 1 favors processes. Individual intervals, six block means. "
            f'<a download href="same-forest-repeatability-{metric}-clair.svg">'
            "Clair SVG</a> and "
            f'<a download href="same-forest-repeatability-{metric}-obscur.svg">'
            "Obscur SVG</a>.</figcaption></figure>"
        )
    parts += [
        '</div><p><a href="same-forest-repeatability-figure.json">',
        "Figure values, renderer and file provenance</a>. Inter is resolved ",
        "from explicit local files into the exported plots. Website text ",
        "uses installed Inter with a system fallback and no remote font request.",
        '</p></main><footer><a href="presentation.json">Site revision and ',
        "file provenance</a>. Presentation is separate from measurement.",
        "</footer></div></body></html>",
    ]
    return "\n".join(part.rstrip() for part in parts) + "\n"


def check_outputs(write=False):
    record = json.loads(DATA.read_text(encoding="utf-8"))
    failed = json.loads(FAILED.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    fields = json.loads(PUBLIC_FIELDS.read_text(encoding="utf-8"))
    validate(record, protocol, public_derivative=True)
    validate_provenance(provenance, record, failed)
    require(
        fields["schema_version"] == 1
        and fields["format"] == "same-forest-public-receipts-v1"
        and fields["changed_fields"] == FIELDS
        and fields["private_originals_modified"] is False
        and fields["search_rerun"] is False,
        "field-removal manifest differs",
    )
    require(
        fields["attempts"]
        == [
            {
                "file": path.name,
                "public_identity": {
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                },
                "private_original_identity": private_identity,
            }
            for path, private_identity in (
                (DATA, PRIVATE_COMPLETE),
                (FAILED, PRIVATE_FAILED),
            )
        ],
        "public derivative identity manifest differs",
    )
    summary = summarize(record)
    for path, text in (
        (REPORT, markdown(record, summary, provenance)),
        (PAGE, webpage(record, summary, provenance)),
    ):
        if write:
            path.write_text(text, encoding="utf-8", newline="\n")
        else:
            require(
                path.read_text(encoding="utf-8") == text,
                "generated report differs: " + path.name,
            )
    return record, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    check_outputs(write=not args.check)
    print("Validated six-block repeatability supplement without executing search")


if __name__ == "__main__":
    main()
