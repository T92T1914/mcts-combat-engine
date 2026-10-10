"""Passive HTML inspection of bounded saved episode data.

The private admission functions are an explicit dependency on episode_record.
Stored claims are displayed without constructing content, state or policy.
"""
from __future__ import annotations

import hashlib
import json
from html import escape
from pathlib import Path
from typing import Any

from game import episode_record as records

HTML_BYTES = 67_108_864
PRESENTATION_SOURCE = {
    "revision": "7a57fe750ff50205a17e1d342106a0d3f2777159",
    "sha256": "889df65e0f4f4eea99a81c535d542e7332b537c000c332402a3ffa6a6cbb15b7",
    "license": "MIT",
}
# A fixed-document subset of the project's pinned Clair/Obscur wrapper.
THEMES = {
    "obscur": {
        "canvas": "#090909", "panel": "#151515", "text": "#f4f4f4",
        "muted": "#bcbcbc", "divider": "#494949", "control": "#252525",
        "hover": "#373737", "border": "#858585", "accent": "#b3c8d8",
        "focus": "#c2d7e6", "warning": "#e3bf79", "code": "#111111",
    },
    "clair": {
        "canvas": "#f8f7f3", "panel": "#fdfcf8", "text": "#242424",
        "muted": "#595854", "divider": "#b8b6ae", "control": "#ecebe6",
        "hover": "#e0ded7", "border": "#7f7d76", "accent": "#365f78",
        "focus": "#315977", "warning": "#805100", "code": "#eeece5",
    },
}
FACES = (
    (400, "normal", "Inter Regular", "Inter-Regular"),
    (400, "italic", "Inter Italic", "Inter-Italic"),
    (600, "normal", "Inter SemiBold", "Inter-SemiBold"),
    (600, "italic", "Inter SemiBold Italic", "Inter-SemiBoldItalic"),
    (700, "normal", "Inter Bold", "Inter-Bold"),
    (700, "italic", "Inter Bold Italic", "Inter-BoldItalic"),
)


class InspectionRuntimeError(RuntimeError):
    """Admitted data cannot produce a complete bounded reading artifact."""


class _Document:
    """Buffer trusted markup and escaped text with an inclusive output limit."""

    def __init__(self) -> None:
        self.parts: list[bytes] = []
        self.size = 0

    def add(self, markup: str) -> None:
        encoded = markup.encode("utf-8")
        self.size += len(encoded)
        if self.size + 1 > HTML_BYTES:
            raise InspectionRuntimeError(
                f"generated HTML exceeds {HTML_BYTES} bytes including final LF")
        self.parts.append(encoded)

    def finish(self) -> bytes:
        return b"".join(self.parts) + b"\n"


def _json(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=indent,
                      allow_nan=False)


def _text(value: Any) -> str:
    # JSON string notation keeps control characters visible rather than active.
    return escape(_json(value), quote=True)


def _fragment(document: _Document, value: Any, pointer: str, title: str) -> None:
    # Callers supply only fixed schema paths or locally enumerated step indices.
    document.add(f'<details><summary>{title}</summary>'
                 f'<pre data-json-pointer="{pointer}">'
                 + escape(_json(value, indent=2), quote=True) + "</pre></details>")


def _facts(document: _Document, values: list[tuple[str, Any]]) -> None:
    document.add("<dl>")
    for label, value in values:
        document.add(f"<dt>{label}</dt><dd>{_text(value)}</dd>")
    document.add("</dl>")


def _declarations(appearance: str) -> str:
    scheme = "light" if appearance == "clair" else "dark"
    colors = "".join(f"--{key}:{value};" for key, value in THEMES[appearance].items())
    return f"color-scheme:{scheme};" + colors


def _css(appearance: str) -> str:
    fonts = "\n".join(
        '@font-face{font-family:"MCTS Episode Inter";'
        f'src:local("{full}"),local("{postscript}");'
        f"font-weight:{weight};font-style:{style};font-display:swap}}"
        for weight, style, full, postscript in FACES
    )
    return fonts + "\n:root{" + _declarations(appearance) + "}" + """
*{box-sizing:border-box}
html{scroll-padding-top:1rem}
body{margin:0;background:var(--canvas);color:var(--text);
font-family:"MCTS Episode Inter",Arial,sans-serif;font-synthesis:none;
font-size:18px;line-height:1.55}
main{max-width:72ch;margin:auto;padding:1.25rem;min-width:0}
h1,h2,h3,h4{font-weight:600;line-height:1.25;overflow-wrap:anywhere}
h1{font-size:2rem}h2{font-size:1.5rem}h3{font-size:1.2rem}h4{font-size:1rem}
strong{font-weight:700}em{font-style:italic}
p,li,dd,td,th{overflow-wrap:anywhere}
section{margin:1.5rem 0;padding:1rem;border:1px solid var(--divider);
border-radius:.4rem;background:var(--panel);min-width:0}
article{border-top:1px solid var(--divider);margin-top:1.5rem;padding-top:1rem}
.muted{color:var(--muted)}.warning{color:var(--warning)}
nav{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0}
a{color:var(--accent);text-decoration:underline;text-underline-offset:.15em}
nav a{display:block;padding:.5rem .75rem;min-height:44px;
border:1px solid var(--border);background:var(--control);border-radius:.3rem}
nav a:hover,summary:hover{background:var(--hover)}
a:focus-visible,summary:focus-visible{outline:3px solid var(--focus);
outline-offset:3px}
dl{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr);gap:.4rem 1rem}
dt{font-weight:600;overflow-wrap:anywhere}dd{margin:0;min-width:0}
table{border-collapse:collapse;width:100%;table-layout:fixed;margin:1rem 0}
caption{text-align:left;font-weight:600;margin:.5rem 0}
th,td{text-align:left;vertical-align:top;border-bottom:1px solid var(--divider);
padding:.4rem}th{font-weight:600}th:first-child,td:first-child{width:4ch}
details{margin:1rem 0;min-width:0}summary{cursor:pointer;padding:.6rem;
border:1px solid var(--border);background:var(--control);font-weight:600;
overflow-wrap:anywhere;min-height:44px}
pre,code{font-family:Consolas,"Liberation Mono",monospace;font-size:.875em;
font-synthesis:none;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}
pre{padding:.8rem;background:var(--code);border:1px solid var(--divider);
max-width:100%;line-height:1.5}footer{color:var(--muted);font-size:.95rem}
@media(max-width:420px){main{padding:.75rem}section{padding:.65rem}
dl{grid-template-columns:minmax(0,1fr)}dd{margin-bottom:.5rem}}
@media(forced-colors:active){section,article,th,td,pre{border-color:CanvasText}
nav a,summary{border-color:ButtonText}.warning,.muted{color:CanvasText}}
""" + "@media print{:root{" + _declarations("clair") + "}" + """
body{font-size:12pt}main{max-width:none;padding:0}nav{display:none}
section{break-inside:auto}summary{background:transparent}}
"""


def _boundary(document: _Document, state: dict[str, Any]) -> None:
    player = state["player"]
    document.add("<h4>Stored player and round</h4>")
    _facts(document, [
        ("Round number", state["round_num"]), ("Player name", player["name"]),
        ("HP", player["hp"]), ("Maximum HP", player["max_hp"]),
        ("Pips", player["pips"]), ("Power pips", player["power_pips"]),
    ])
    document.add('<table><caption>Hand in stored order</caption><thead><tr>'
                 '<th scope="col">Index</th><th scope="col">Stored name</th>'
                 '<th scope="col">Type, element, pip cost</th></tr></thead><tbody>')
    for index, card in enumerate(state["hand"]):
        fields = [card["card_type"], card["element"], card["pip_cost"]]
        document.add(f"<tr><td>{index}</td><td>{_text(card['name'])}</td>"
                     f"<td>{_text(fields)}</td></tr>")
    document.add("</tbody></table>")
    if not state["hand"]:
        document.add("<p>The stored hand is empty.</p>")
    document.add('<table><caption>Enemies in original stored slots</caption>'
                 '<thead><tr><th scope="col">Slot</th><th scope="col">Stored name</th>'
                 '<th scope="col">HP / maximum HP</th></tr></thead><tbody>')
    for index, enemy in enumerate(state["enemies"]):
        document.add(f"<tr><td>{index}</td><td>{_text(enemy['name'])}</td>"
                     f"<td>{_text(enemy['hp'])} / {_text(enemy['max_hp'])}</td></tr>")
    document.add("</tbody></table><p class=\"muted\">Dead entries retain their "
                 "original slot. Complete modifiers, damage-over-time, rules and "
                 "nullable fields remain in the expandable stored JSON.</p>")


def _reference(document: _Document, label: str, index: int | None,
               entries: list[dict[str, Any]], kind: str) -> None:
    document.add(f"<dt>{label}</dt><dd>")
    if index is None:
        document.add("<code>null</code> (stored index)")
    elif index < len(entries):
        document.add(f"Stored index {_text(index)} refers to stored name "
                     + _text(entries[index]["name"]))
    else:
        document.add(f'<span class="warning">Index {_text(index)}: no entry at '
                     f"this index in the stored {kind}.</span>")
    document.add("</dd>")


def _render(record: dict[str, Any], captured: bytes, appearance: str) -> bytes:
    document = _Document()
    document.add('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width,initial-scale=1">'
                 "<title>Saved episode inspection</title><style>"
                 + _css(appearance) + "</style></head><body><main>")
    document.add('<header id="overview"><h1>Saved episode inspection</h1>'
                 "<p><strong>Passive inspection of stored data.</strong> Admission "
                 "checks the saved schema. It does not authenticate origin, verify "
                 "stored runtime claims or establish that a policy chose these "
                 "actions. No environment, replay or search runs here.</p>"
                 "<p><em>The record can be read without its original content or "
                 "a matching recorded runtime.</em></p></header>")
    _facts(document, [("Captured record bytes", len(captured)),
                      ("Captured record SHA-256", hashlib.sha256(captured).hexdigest()),
                      ("Screen edition", appearance)])
    document.add('<nav aria-label="Report sections"><a href="#overview">Overview</a>'
                 '<a href="#provenance">Stored provenance</a>'
                 '<a href="#scenario">Scenario and deck</a>'
                 '<a href="#initial">Initial boundary</a>')
    for index in range(len(record["steps"])):
        document.add(f'<a href="#step-{index}">Step {index}</a>')
    document.add('<a href="#final">Final boundary</a></nav>')
    _fragment(document, record["format"], "/format", "Stored format")
    _fragment(document, record["schema_version"], "/schema_version", "Stored version")
    document.add('<section id="provenance"><h2>Stored provenance and configuration</h2>'
                 "<p>These content identities, runtime labels and file hash maps "
                 "are stored claims. Hashes and comparison filenames are plain "
                 "text. The captured record digest above identifies the exact "
                 "input bytes read by this invocation.</p>")
    for name, title in (
        ("content", "Complete content identities"),
        ("implementation", "Complete stored implementation and runtime"),
        ("configuration", "Complete stored search configuration"),
        ("environment_rng", "Complete stored environment RNG checkpoints"),
    ):
        _fragment(document, record[name], f"/{name}", title)
    _facts(document, [
        ("Environment seed", record["scenario"]["environment_seed"]),
        ("Search seed", record["configuration"]["search_seed"]),
    ])
    document.add('</section><section id="scenario"><h2>Scenario and ordered deck</h2>')
    _facts(document, [("Scenario name", record["scenario"]["name"]),
                      ("Deck entries", len(record["scenario"]["deck"]))])
    _fragment(document, record["scenario"], "/scenario", "Complete scenario and deck")
    document.add('</section><section id="initial">'
                 '<h2>Scenario-created initial boundary</h2>'
                 "<p>Stored initial state before the runner's first refill and "
                 "decision. The first pre-action boundary can include that refill.</p>")
    _boundary(document, record["initial_state"])
    _fragment(document, record["initial_state"], "/initial_state",
              "Complete initial state")
    steps = record["steps"]
    document.add('</section><section id="steps" data-json-pointer="/steps" '
                 f'data-step-count="{len(steps)}"><h2>Recorded decisions</h2>'
                 "<p>Each boundary is after refill and before its own recorded "
                 "action. Index references use that same boundary only and do not "
                 "prove legality. Between successive boundaries, the prior action, "
                 "round effects and next refill can all contribute. No intermediate "
                 "random event or isolated action effect is inferred.</p>")
    if not steps:
        document.add("<p>No recorded decisions. Stored steps: <code>[]</code>.</p>")
    for index, step in enumerate(steps):
        document.add(f'<article id="step-{index}"><h3>Step {index}: after refill, '
                     "before recorded action</h3>")
        _boundary(document, step["state"])
        action = step["action"]
        document.add("<h4>Stored action and same-boundary references</h4>")
        _facts(document, [("Stored action label", action["label"]),
                          ("Raw index pair [card_idx, target_idx]",
                           [action["card_idx"], action["target_idx"]])])
        document.add("<dl>")
        _reference(document, "Card reference", action["card_idx"],
                   step["state"]["hand"], "hand")
        _reference(document, "Enemy reference", action["target_idx"],
                   step["state"]["enemies"], "enemy slots")
        document.add("</dl><p class=\"muted\">Null stays null. The stored label is "
                     "retained without deriving Pass or another action "
                     "description.</p>")
        _fragment(document, step, f"/steps/{index}", "Complete step, state and action")
        document.add("</article>")
    final = record["final"]
    document.add('</section><section id="final"><h2>Stored final completion</h2>'
                 "<p>After the last completed action and round, without another "
                 "decision refill, or immediate terminal completion with zero steps. "
                 "This is not a pre-action boundary. A final hand can have "
                 "six cards.</p>")
    _facts(document, [("Raw stored score", final["score"]),
                      ("Stored terminal result", final["terminal_result"]),
                      ("Completed rounds", final["rounds"]),
                      ("Stored termination", final["termination"])])
    document.add("<p>A round-limit score is the model's stored heuristic, not a "
                 "calibrated win probability. Terminal and completion values are "
                 "displayed as recorded, without recomputing them.</p>")
    _boundary(document, final["state"])
    _fragment(document, final, "/final", "Complete final state and completion")
    document.add("</section><footer><p>Body typography uses local Inter when its "
                 "declared faces are available, with Arial and the browser's "
                 "sans-serif fallback otherwise. JSON intentionally uses monospace. "
                 "No font is bundled or downloaded. Screen appearance is fixed "
                 "for this document. Print uses Clair.</p><p>Pinned Clair/Obscur "
                 "roles, MIT. Revision " + PRESENTATION_SOURCE["revision"]
                 + ". Original normalized token SHA-256 "
                 + PRESENTATION_SOURCE["sha256"]
                 + ".</p></footer></main></body></html>")
    return document.finish()


def inspection_html(record_path: Path, *, appearance: str = "obscur") -> bytes:
    """Read once and return a complete passive HTML document without file writes."""
    if not isinstance(appearance, str) or appearance not in THEMES:
        raise records.EpisodeInputError("appearance: choose obscur or clair")
    captured = records._read(record_path, "record", records.RECORD_BYTES)
    record = records.validate_record(records._parse(captured, "record", 200_000,
                                                    10**300))
    try:
        return _render(record, captured, appearance)
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise InspectionRuntimeError("admitted record cannot be rendered") from exc


# This format has its own passive boundary. The episode renderer above is unchanged.
DECISION_FIELDS = (
    "format", "schema_version", "status", "search_performed", "source_record",
    "selection", "selected_state", "stored_action", "stored_provenance",
    "implementation", "identity_comparisons", "value_semantics", "configuration",
    "work", "elapsed_seconds", "legal_actions", "ranking", "recommendation",
)
V2_FIELDS = {"root_encounter_order", "derivation"}
EXPLORATIONS = (0.6, 1.2, 2.4)
FINAL_ACTION_RULES = {"mean_visits", "visits_mean"}


def decision_ranking(report: dict, rule: str) -> list[dict]:
    """Rerank saved sufficient statistics only, preserving encounter ties."""
    records._choice(rule, "final_action_rule", FINAL_ACTION_RULES)
    rows = {(row["card_idx"], row["target_idx"]): row
            for row in report["legal_actions"]}
    order = report["root_encounter_order"]
    names = (("mean_shaped_reward", "visits") if rule == "mean_visits"
             else ("visits", "mean_shaped_reward"))
    return sorted(order, key=lambda action: tuple(
        rows[(action["card_idx"], action["target_idx"])][name] for name in names),
        reverse=True)


def _report_implementation(value: Any, location: str) -> None:
    """Admit the report producer's role without observing this reader's runtime."""
    obj = records._object(value, location, {
        "python", "python_implementation", "platform", "engine_import_kind",
        "distribution_version", "distribution_matches_import",
        "engine_files_sha256", "example_files_sha256", "entrypoint_files_sha256",
        "machine", "pointer_bits", "python_full_version", "python_build",
        "python_cache_tag", "rng_state_version",
    })
    for name in ("python", "python_implementation", "platform", "machine"):
        records._string(obj[name], f"{location}/{name}")
    records._string(obj["python_full_version"], f"{location}/python_full_version",
                    high=2048)
    for index, item in enumerate(records._array(
            obj["python_build"], f"{location}/python_build", 2, 2)):
        records._string(item, f"{location}/python_build/{index}", low=0, high=2048)
    for name in ("python_cache_tag", "distribution_version"):
        if obj[name] is not None:
            records._string(obj[name], f"{location}/{name}")
    records.integer(obj["pointer_bits"], f"{location}/pointer_bits", 32, 64)
    if obj["pointer_bits"] not in (32, 64):
        records._error(f"{location}/pointer_bits", "must be 32 or 64")
    records.integer(obj["rng_state_version"], f"{location}/rng_state_version", 3, 3)
    records._choice(obj["engine_import_kind"], f"{location}/engine_import_kind",
                    {"source", "site-packages"})
    records._boolean(obj["distribution_matches_import"],
                     f"{location}/distribution_matches_import")
    for name in ("engine_files_sha256", "example_files_sha256",
                 "entrypoint_files_sha256"):
        records._hash_map(obj[name], f"{location}/{name}")
    if any(not name.startswith("game/") for name in obj["example_files_sha256"]):
        records._error(f"{location}/example_files_sha256",
                       "comparison names must begin game/")
    if set(obj["entrypoint_files_sha256"]) != {"decide_episode.py"}:
        records._error(f"{location}/entrypoint_files_sha256",
                       "must identify decide_episode.py")


def _stored_provenance(value: Any) -> dict:
    location = "/stored_provenance"
    obj = records._object(value, location, {
        "content", "scenario", "configuration", "implementation", "environment_rng",
    })
    for name, validator in (
        ("content", records._content_identity),
        ("implementation", records._implementation),
    ):
        try:
            validator(obj[name])
        except records.EpisodeInputError as exc:
            raise records.EpisodeInputError(f"{location}/{name}: {exc}") from exc
    scenario = records._object(obj["scenario"], f"{location}/scenario",
                               {"name", "environment_seed", "deck"})
    records._string(scenario["name"], f"{location}/scenario/name")
    records.integer(scenario["environment_seed"],
                    f"{location}/scenario/environment_seed",
                    records.SEED_MIN, records.SEED_MAX)
    for index, card in enumerate(records._array(
            scenario["deck"], f"{location}/scenario/deck", 1, 128)):
        records._card(card, f"{location}/scenario/deck/{index}")
    config = records._object(obj["configuration"], f"{location}/configuration", {
        "method", "mode", "search_seed", "search_rng_mode", "max_rounds",
        "max_sims_per_decision", "horizon_rounds", "max_transitions_per_decision",
        "exploration", "time_budget_ms", "parallel", "workers", "priors",
        "policy_rng",
    })
    try:
        expected = records._configuration(
            config["max_rounds"], config["max_sims_per_decision"],
            config["horizon_rounds"], config["search_seed"])
    except records.EpisodeInputError as exc:
        raise records.EpisodeInputError(
            f"{location}/configuration: {exc}") from exc
    if not records._equal(config, expected):
        records._error(f"{location}/configuration",
                       "unsupported recording policy/configuration")
    rng = records._object(obj["environment_rng"], f"{location}/environment_rng", {
        "checkpoint_scheme", "state_version", "after_scenario_sha256", "final_sha256",
    })
    records._choice(rng["checkpoint_scheme"],
                    f"{location}/environment_rng/checkpoint_scheme",
                    {"python-random-getstate-json-v1"})
    records.integer(rng["state_version"], f"{location}/environment_rng/state_version",
                    3, 3)
    for name in ("after_scenario_sha256", "final_sha256"):
        records._digest(rng[name], f"{location}/environment_rng/{name}")
    return obj


def _report_configuration(value: Any, version: int = 1) -> dict:
    location = "/configuration"
    required = {
        "method", "mode", "seed", "search_rng_mode", "max_sims", "horizon_rounds",
        "max_transitions", "exploration", "time_budget_ms", "priors", "parallel",
        "workers",
    }
    if version == 2:
        required |= {"final_action_rule", "tie_break"}
    obj = records._object(value, location, required)
    for name, expected in (
        ("method", "mcts"), ("mode", "serial_clockless"),
        ("search_rng_mode", "new_seed_per_decision"),
    ):
        records._choice(obj[name], f"{location}/{name}", {expected})
    records.integer(obj["seed"], f"{location}/seed", records.SEED_MIN,
                    records.SEED_MAX)
    sims = records.integer(obj["max_sims"], f"{location}/max_sims", 0, 64)
    horizon = records.integer(obj["horizon_rounds"],
                              f"{location}/horizon_rounds", 1, 8)
    records.integer(obj["max_transitions"], f"{location}/max_transitions",
                    sims * horizon, sims * horizon)
    if version == 1:
        records._number(obj["exploration"], f"{location}/exploration", 1.2, 1.2)
    else:
        records._number(obj["exploration"], f"{location}/exploration", 0.6, 2.4)
        if obj["exploration"] not in EXPLORATIONS:
            records._error(f"{location}/exploration", "use 0.6, 1.2 or 2.4")
        records._choice(obj["final_action_rule"], f"{location}/final_action_rule",
                        FINAL_ACTION_RULES)
        records._choice(obj["tie_break"], f"{location}/tie_break",
                        {"root_encounter_order"})
    for name in ("time_budget_ms", "priors", "workers"):
        if obj[name] is not None:
            records._error(f"{location}/{name}", "must be null")
    if obj["parallel"] is not False:
        records._error(f"{location}/parallel", "must be false")
    return obj


def _report_action(value: Any, location: str, *, label: bool = False,
                   stored: bool = False) -> tuple[int | None, int | None]:
    keys = {"card_idx", "target_idx"} | ({"label"} if label else set())
    obj = records._object(value, location, keys)
    for name, high in (("card_idx", 6), ("target_idx", 7)):
        if obj[name] is not None:
            records.integer(obj[name], f"{location}/{name}", 0, high)
    if not stored and obj["card_idx"] is None and obj["target_idx"] is not None:
        records._error(location, "a Pass identity requires both indices null")
    if label:
        records._string(obj["label"], f"{location}/label", high=260)
    return obj["card_idx"], obj["target_idx"]


def _report_statistics(obj: dict, config: dict) -> None:
    location = "/work"
    work = records._object(obj["work"], location, {
        "simulations", "transitions", "unused_transitions", "stop_reasons",
    })
    records.integer(work["simulations"], f"{location}/simulations", 0, 64)
    for name in ("transitions", "unused_transitions"):
        records.integer(work[name], f"{location}/{name}", 0, 512)
    reasons = records._array(work["stop_reasons"], f"{location}/stop_reasons", 0, 2)
    allowed = {"zero_requested_simulations"} if not config["max_sims"] else {
        "simulation_cap", "transition_allowance"}
    for index, reason in enumerate(reasons):
        records._choice(reason, f"{location}/stop_reasons/{index}", allowed)
    if len(set(reasons)) != len(reasons):
        records._error(f"{location}/stop_reasons", "reasons must be unique")
    rows: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    for index, row in enumerate(records._array(
            obj["legal_actions"], "/legal_actions", 1, 57)):
        path = f"/legal_actions/{index}"
        row = records._object(row, path, {
            "card_idx", "target_idx", "label", "status", "visits", "value_sum",
            "mean_shaped_reward",
        })
        identity = _report_action(
            {name: row[name] for name in ("card_idx", "target_idx", "label")},
            path, label=True)
        if identity in rows:
            records._error(path, "duplicate raw action identity")
        rows[identity] = row
        records._choice(row["status"], f"{path}/status", {"sampled", "unvisited"})
        visits = records.integer(row["visits"], f"{path}/visits", 0, 64)
        records._number(row["value_sum"], f"{path}/value_sum", -10**300, 10**300)
        mean = row["mean_shaped_reward"]
        if row["status"] == "unvisited":
            if visits != 0 or row["value_sum"] != 0 or mean is not None:
                records._error(path, "unvisited requires zero visits/sum and null mean")
        else:
            if visits == 0 or mean is None:
                records._error(path, "sampled requires positive visits and a mean")
            records._number(mean, f"{path}/mean_shaped_reward", -10**300, 10**300)
            if mean != row["value_sum"] / visits:
                records._error(f"{path}/mean_shaped_reward",
                               "must equal the saved value sum divided by visits")
    ranking: list[tuple[int | None, int | None]] = []
    for index, action in enumerate(records._array(obj["ranking"], "/ranking", 0, 57)):
        identity = _report_action(action, f"/ranking/{index}")
        if identity in ranking:
            records._error(f"/ranking/{index}", "duplicate raw action identity")
        ranking.append(identity)
    sampled = {identity for identity, row in rows.items()
               if row["status"] == "sampled"}
    if set(ranking) != sampled:
        records._error("/ranking", "must contain each sampled row exactly once")
    if sum(row["visits"] for row in rows.values()) != work["simulations"]:
        records._error("/work/simulations", "must equal the saved visits sum")
    recommendation = obj["recommendation"]
    if ranking:
        identity = _report_action(recommendation, "/recommendation", label=True)
        if (identity != ranking[0]
                or recommendation["label"] != rows[ranking[0]]["label"]):
            records._error("/recommendation",
                           "must match the first ranking identity and its saved label")
    elif recommendation is not None:
        records._error("/recommendation", "empty ranking requires null")
    if config["max_sims"]:
        if obj["status"] != "decision" or obj["search_performed"] is not True:
            records._error("/status", "positive requested work requires decision/true")
        if (work["simulations"] != config["max_sims"]
                or work["transitions"] > config["max_transitions"]
                or work["unused_transitions"] != (
                    config["max_transitions"] - work["transitions"])
                or not ranking):
            records._error("/work", "counts must agree with positive requested work")
    elif (obj["status"] != "no_work" or obj["search_performed"] is not False
          or obj["elapsed_seconds"] != 0 or work["simulations"] != 0
          or work["transitions"] != 0 or work["unused_transitions"] != 0
          or reasons != ["zero_requested_simulations"] or ranking
          or recommendation is not None or sampled):
        records._error("/work",
                       "zero requested work requires a complete no-work report")


def validate_decision_report(value: Any) -> dict:
    """Admit stored representation only, without reconstruction or model calls."""
    records._envelope(value, 200_000, 10**300)
    if not isinstance(value, dict):
        records._error("/report", "must be an object")
    version = records.integer(value.get("schema_version"), "/schema_version", 1, 2)
    obj = records._object(value, "/report", set(DECISION_FIELDS) |
                          (V2_FIELDS if version == 2 else set()))
    records._choice(obj["format"], "/format", {"mcts-episode-decision-report"})
    records._choice(obj["status"], "/status", {"decision", "no_work"})
    records._boolean(obj["search_performed"], "/search_performed")
    source = records._object(obj["source_record"], "/source_record",
                             {"bytes", "sha256"})
    records.integer(source["bytes"], "/source_record/bytes", 1, records.RECORD_BYTES)
    records._digest(source["sha256"], "/source_record/sha256")
    selected = records._object(obj["selection"], "/selection",
                               {"step_index", "round_num", "state_pointer"})
    step = records.integer(selected["step_index"], "/selection/step_index", 0, 29)
    records.integer(selected["round_num"], "/selection/round_num", step + 1, step + 1)
    if selected["state_pointer"] != f"/steps/{step}/state":
        records._error("/selection/state_pointer",
                       "must name the selected episode state")
    records._state(obj["selected_state"], "/selected_state")
    if obj["selected_state"]["round_num"] != selected["round_num"]:
        records._error("/selected_state/round_num", "must agree with selection")
    _report_action(obj["stored_action"], "/stored_action", label=True, stored=True)
    old = _stored_provenance(obj["stored_provenance"])
    if selected["round_num"] > old["configuration"]["max_rounds"]:
        records._error("/selection/round_num", "exceeds the stored recording round cap")
    _report_implementation(obj["implementation"], "/implementation")
    claims = records._object(obj["identity_comparisons"], "/identity_comparisons", {
        "engine_files_equal", "example_files_equal", "runtime_fields_equal",
        "entrypoint_roles",
    })
    for name in ("engine_files_equal", "example_files_equal", "runtime_fields_equal"):
        records._boolean(claims[name], f"/identity_comparisons/{name}")
    roles = records._object(claims["entrypoint_roles"],
                            "/identity_comparisons/entrypoint_roles",
                            {"recorded", "current", "same_role"})
    for name, expected in (
        ("recorded", "episode.py"), ("current", "decide_episode.py"),
    ):
        records._choice(roles[name], f"/identity_comparisons/entrypoint_roles/{name}",
                        {expected})
    if roles["same_role"] is not False:
        records._error("/identity_comparisons/entrypoint_roles/same_role",
                       "the saved entrypoint roles must remain distinct")
    records._string(obj["value_semantics"], "/value_semantics", high=2048)
    records._number(obj["elapsed_seconds"], "/elapsed_seconds", 0, 10**300)
    config = _report_configuration(obj["configuration"], version)
    _report_statistics(obj, config)
    if version == 2:
        order = []
        for index, action in enumerate(records._array(
                obj["root_encounter_order"], "/root_encounter_order", 0, 57)):
            identity = _report_action(action, f"/root_encounter_order/{index}")
            if identity in order:
                records._error("/root_encounter_order", "duplicate identity")
            order.append(identity)
        sampled = {(row["card_idx"], row["target_idx"])
                   for row in obj["legal_actions"] if row["visits"]}
        if set(order) != sampled:
            records._error("/root_encounter_order",
                           "must contain each sampled identity exactly once")
        if obj["ranking"] != decision_ranking(obj, config["final_action_rule"]):
            records._error("/ranking",
                           "disagrees with declared rule and encounter ties")
        if obj["derivation"] is not None:
            path = "/derivation"
            derived = records._object(obj["derivation"], path, {
                "operation", "source_report", "cell_index",
                "source_final_action_rule", "new_search_performed",
            })
            records._choice(derived["operation"], path + "/operation",
                            {"stability_cell_extraction"})
            source = records._object(derived["source_report"], path + "/source_report",
                                     {"bytes", "sha256", "status"})
            records.integer(source["bytes"], path + "/source_report/bytes",
                            1, records.RECORD_BYTES)
            records._digest(source["sha256"], path + "/source_report/sha256")
            records._choice(source["status"], path + "/source_report/status",
                            {"complete", "incomplete"})
            records.integer(derived["cell_index"], path + "/cell_index", 0, 47)
            records._choice(derived["source_final_action_rule"],
                            path + "/source_final_action_rule", {"mean_visits"})
            if derived["new_search_performed"] is not False:
                records._error(path + "/new_search_performed", "must be false")
    return obj


def stability_configuration(seeds: Any, explorations: Any, horizon: Any) -> dict:
    """Admit the complete finite grid before any fresh-search operation."""
    seeds = records._array(seeds, "seeds", 2, 16)
    for index, seed in enumerate(seeds):
        records.integer(seed, f"seeds/{index}", records.SEED_MIN, records.SEED_MAX)
    if len(set(seeds)) != len(seeds):
        records._error("seeds", "must be distinct")
    if len({abs(seed) for seed in seeds}) != len(seeds):
        records._error("seeds",
                       "must have distinct absolute values for RNG initialization")
    explorations = records._array(explorations, "explorations", 1, 3)
    for index, coefficient in enumerate(explorations):
        records._number(coefficient, f"explorations/{index}", 0.6, 2.4)
        if coefficient not in EXPLORATIONS:
            records._error(f"explorations/{index}", "use 0.6, 1.2 or 2.4")
    if len(set(explorations)) != len(explorations):
        records._error("explorations", "must be distinct")
    horizon = records.integer(horizon, "horizon", 1, 8)
    calls = len(seeds) * len(explorations)
    return {"seeds": list(seeds), "explorations": list(explorations),
            "max_sims": 64, "horizon_rounds": horizon,
            "max_transitions_per_cell": 64 * horizon,
            "maximum_search_calls": calls, "maximum_simulations": calls * 64,
            "maximum_transitions": calls * 64 * horizon}


def _identity(action: dict) -> tuple:
    return action["card_idx"], action["target_idx"]


def _selector_cell(report: dict, rule: str) -> dict:
    ranking = decision_ranking(report, rule)
    rows = {_identity(row): row for row in report["legal_actions"]}
    first = rows[_identity(ranking[0])]
    primary = "mean_shaped_reward" if rule == "mean_visits" else "visits"
    return {
        "primary_ties": sum(rows[_identity(action)][primary] == first[primary]
                            for action in ranking),
        "complete_ties": sum(
            rows[_identity(action)]["visits"] == first["visits"] and
            rows[_identity(action)]["mean_shaped_reward"] == first["mean_shaped_reward"]
            for action in ranking),
        "mean_gap": (first["mean_shaped_reward"] -
                     rows[_identity(ranking[1])]["mean_shaped_reward"]
                     if len(ranking) > 1 else None),
        "visit_gap": (first["visits"] - rows[_identity(ranking[1])]["visits"]
                      if len(ranking) > 1 else None),
    }


def stability_diagnostics(cells: list[dict], configuration: dict) -> dict:
    """Descriptive arithmetic from admitted saved reports; never runs search."""
    groups = []
    by_coefficient = {}
    for coefficient in configuration["explorations"]:
        group = [cell for cell in cells
                 if cell["configuration"]["exploration"] == coefficient]
        choices = {rule: [_identity(decision_ranking(cell, rule)[0]) for cell in group]
                   for rule in sorted(FINAL_ACTION_RULES)}
        result = {"exploration": coefficient,
                  "selector_disagreements": sum(a != b for a, b in zip(
                      choices["mean_visits"], choices["visits_mean"], strict=True)),
                  "cells": [{"seed": cell["configuration"]["seed"],
                             **{rule: _selector_cell(cell, rule)
                                for rule in sorted(FINAL_ACTION_RULES)}}
                            for cell in group]}
        for rule, selected in choices.items():
            counts = {identity: selected.count(identity) for identity in
                      dict.fromkeys(selected)}
            result[rule] = {
                "action_frequencies": [{"card_idx": card, "target_idx": target,
                                        "count": count}
                                       for (card, target), count in counts.items()],
                "modal_count": max(counts.values()),
                "seed_pair_disagreements": sum(
                    selected[left] != selected[right]
                    for left in range(len(selected))
                    for right in range(left + 1, len(selected))),
                "seed_pair_denominator": len(selected) * (len(selected) - 1) // 2,
            }
        groups.append(result)
        by_coefficient[coefficient] = choices
    coefficients = configuration["explorations"]
    comparisons = []
    for left in range(len(coefficients)):
        for right in range(left + 1, len(coefficients)):
            a, b = coefficients[left], coefficients[right]
            comparisons.append({"left": a, "right": b,
                                "denominator": len(configuration["seeds"]),
                                **{rule: sum(x != y for x, y in zip(
                                    by_coefficient[a][rule], by_coefficient[b][rule],
                                    strict=True))
                                   for rule in sorted(FINAL_ACTION_RULES)}})
    return {"groups": groups, "coefficient_disagreements": comparisons}


def stability_work(cells: list[dict]) -> dict:
    return {"completed_search_calls": len(cells),
            **{name: sum(cell["work"][name] for cell in cells)
               for name in ("simulations", "transitions", "unused_transitions")}}


def validate_stability_report(value: Any) -> dict:
    """Admit a complete grid or truthful completed prefix without model work."""
    records._envelope(value, 200_000, 10**300)
    obj = records._object(value, "/stability", {
        "format", "schema_version", "status", "reference_decision", "configuration",
        "cells", "work", "diagnostics", "failure",
    })
    records._choice(obj["format"], "/format", {"mcts-episode-stability-report"})
    records.integer(obj["schema_version"], "/schema_version", 1, 1)
    records._choice(obj["status"], "/status", {"complete", "incomplete"})
    config = records._object(obj["configuration"], "/configuration", {
        "seeds", "explorations", "max_sims", "horizon_rounds",
        "max_transitions_per_cell", "maximum_search_calls", "maximum_simulations",
        "maximum_transitions",
    })
    expected = stability_configuration(config["seeds"], config["explorations"],
                                       config["horizon_rounds"])
    if records.canonical(config) != records.canonical(expected):
        records._error("/configuration", "declared work must match the supported grid")
    reference = validate_decision_report(obj["reference_decision"])
    if (reference["schema_version"] != 2 or reference["status"] != "no_work"
            or reference["derivation"] is not None
            or reference["configuration"]["final_action_rule"] != "mean_visits"
            or reference["configuration"]["seed"] != config["seeds"][0]
            or reference["configuration"]["exploration"] != config["explorations"][0]
            or reference["configuration"]["horizon_rounds"] !=
            config["horizon_rounds"]):
        records._error("/reference_decision", "requires the admitted no-work boundary")
    cells = records._array(obj["cells"], "/cells", 0, config["maximum_search_calls"])
    grid = [(coefficient, seed) for coefficient in config["explorations"]
            for seed in config["seeds"]]
    shared = ("source_record", "selection", "selected_state", "stored_action",
              "stored_provenance", "implementation", "identity_comparisons",
              "value_semantics")
    for index, cell in enumerate(cells):
        try:
            validate_decision_report(cell)
        except records.EpisodeInputError as exc:
            raise records.EpisodeInputError(f"/cells/{index}: {exc}") from exc
        current = cell["configuration"]
        if (cell["schema_version"] != 2 or cell["status"] != "decision"
                or cell["derivation"] is not None
                or current["final_action_rule"] != "mean_visits"
                or (current["exploration"], current["seed"]) != grid[index]
                or current["max_sims"] != 64
                or current["horizon_rounds"] != config["horizon_rounds"]):
            records._error(f"/cells/{index}", "does not match the declared grid cell")
        for name in shared:
            if records.canonical(cell[name]) != records.canonical(reference[name]):
                records._error(f"/cells/{index}/{name}", "differs from sweep boundary")
        choices = [{name: row[name] for name in ("card_idx", "target_idx", "label")}
                   for row in cell["legal_actions"]]
        reference_choices = [
            {name: row[name] for name in ("card_idx", "target_idx", "label")}
            for row in reference["legal_actions"]]
        if records.canonical(choices) != records.canonical(reference_choices):
            records._error(f"/cells/{index}/legal_actions",
                           "differs from boundary choices")
    if records.canonical(obj["work"]) != records.canonical(stability_work(cells)):
        records._error("/work", "must equal completed constituent work")
    if obj["status"] == "complete":
        if len(cells) != len(grid) or obj["failure"] is not None:
            records._error("/status",
                           "complete requires every declared cell and no failure")
        if records.canonical(obj["diagnostics"]) != records.canonical(
                stability_diagnostics(cells, config)):
            records._error("/diagnostics",
                           "does not match saved constituent statistics")
    else:
        if obj["diagnostics"] is not None:
            records._error("/diagnostics",
                           "incomplete sweeps have no complete diagnostic")
        failure = records._object(obj["failure"], "/failure",
                                  {"stage", "cell_index", "message", "interrupted"})
        records._choice(failure["stage"], "/failure/stage", {"search", "finalization"})
        records._string(failure["message"], "/failure/message", high=2048)
        records._boolean(failure["interrupted"], "/failure/interrupted")
        if failure["stage"] == "search":
            records.integer(failure["cell_index"], "/failure/cell_index", 0, 47)
            if failure["cell_index"] != len(cells) or len(cells) == len(grid):
                records._error("/failure/cell_index",
                               "must name the next unfinished cell")
        else:
            if len(cells) != len(grid):
                records._error("/failure/stage",
                               "finalization requires every declared cell")
            if failure["cell_index"] is not None:
                records._error("/failure/cell_index",
                               "finalization has no unfinished search")
    return obj


def extract_stability_decision(path: Path, *, cell_index: int,
                               final_action_rule: str = "mean_visits") -> dict:
    """Extract and optionally rerank captured statistics without observing runtime."""
    cell_index = records.integer(cell_index, "cell_index", 0, 47)
    records._choice(final_action_rule, "final_action_rule", FINAL_ACTION_RULES)
    captured = records._read(path, "stability report", records.RECORD_BYTES)
    report = validate_stability_report(records._parse(
        captured, "stability report", 200_000, 10**300))
    if cell_index >= len(report["cells"]):
        records._error("cell_index", "selected cell has no completed decision")
    source = report["cells"][cell_index]
    decision = {**source, "configuration": {
        **source["configuration"], "final_action_rule": final_action_rule}}
    decision["ranking"] = decision_ranking(decision, final_action_rule)
    chosen = decision["ranking"][0]
    row = next(row for row in decision["legal_actions"]
               if _identity(row) == _identity(chosen))
    decision["recommendation"] = {**chosen, "label": row["label"]}
    decision["derivation"] = {
        "operation": "stability_cell_extraction",
        "source_report": {"bytes": len(captured),
                          "sha256": hashlib.sha256(captured).hexdigest(),
                          "status": report["status"]},
        "cell_index": cell_index, "source_final_action_rule": "mean_visits",
        "new_search_performed": False,
    }
    validate_decision_report(decision)
    records.output_bytes(decision)
    return decision


def _report_references(document: _Document, action: dict, state: dict) -> None:
    _facts(document, [("Saved label", action["label"]),
                      ("Raw index pair [card_idx, target_idx]",
                       [action["card_idx"], action["target_idx"]])])
    document.add("<dl>")
    _reference(document, "Card reference", action["card_idx"], state["hand"], "hand")
    _reference(document, "Enemy reference", action["target_idx"],
               state["enemies"], "enemy slots")
    document.add("</dl>")


def _render_decision(record: dict, captured: bytes, appearance: str) -> bytes:
    document = _Document()
    document.add('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width,initial-scale=1">'
                 "<title>Saved decision report inspection</title><style>"
                 + _css(appearance) + "</style></head><body><main>")
    document.add('<header id="overview"><h1>Saved decision report inspection</h1>'
                 "<p><strong>Passive inspection of reported choices.</strong> "
                 "Admission checks the saved schema and elementary representation "
                 "consistency. It does not establish that search occurred, choices "
                 "are legal, counters are honest or values are correct. No state "
                 "reconstruction, environment, replay, search or RNG runs here.</p>"
                 "<p><em>Recording provenance, report-producer provenance and this "
                 "passive capture are separate roles.</em></p></header>")
    _facts(document, [
        ("Captured decision report bytes", len(captured)),
        ("Captured decision report SHA-256", hashlib.sha256(captured).hexdigest()),
        ("Claimed original episode bytes", record["source_record"]["bytes"]),
        ("Claimed original episode SHA-256", record["source_record"]["sha256"]),
        ("Screen edition", appearance),
    ])
    document.add('<nav aria-label="Report sections">')
    for name, title in (
        ("overview", "Overview"), ("selection", "Selected boundary"),
        ("boundary", "Stored state"), ("stored-action", "Old action"),
        ("alternatives", "Reported alternatives"), ("ranking", "Ranking"),
        ("work", "Reported work"), ("provenance", "Saved provenance"),
    ):
        document.add(f'<a href="#{name}">{title}</a>')
    document.add("</nav>")
    for name, title in (
        ("format", "Stored format"), ("schema_version", "Stored version"),
        ("status", "Stored status"), ("search_performed", "Saved search claim"),
        ("source_record", "Claimed original episode identity"),
    ):
        _fragment(document, record[name], f"/{name}", title)
    document.add('<section id="selection"><h2>Selected pre-action boundary</h2>'
                 "<p>The saved selection points into the original episode's state "
                 "after refill and before its own recorded action. This pointer "
                 "does not address an array in this report. The original episode "
                 "is not opened or checked.</p>")
    _facts(document, [
        ("Original step index", record["selection"]["step_index"]),
        ("Round number", record["selection"]["round_num"]),
        ("Claimed original state pointer", record["selection"]["state_pointer"]),
    ])
    _fragment(document, record["selection"], "/selection", "Complete saved selection")
    document.add('</section><section id="boundary"><h2>Complete selected state</h2>')
    state = record["selected_state"]
    _boundary(document, state)
    _fragment(document, state, "/selected_state", "Complete selected state")
    document.add('</section><section id="stored-action"><h2>Retained old action</h2>'
                 "<p>This is the action retained from the original recording, not "
                 "the reported current recommendation. Its label is kept literal.</p>")
    _report_references(document, record["stored_action"], state)
    _fragment(document, record["stored_action"], "/stored_action",
              "Complete retained old action")
    document.add('</section><section id="alternatives"><h2>Reported alternatives</h2>'
                 "<p>Rows retain saved order and raw indices. References use only "
                 "the selected saved hand and original enemy slots. Missing entries "
                 "are visibly unresolved. No legality or completeness is recomputed. "
                 "An unvisited row has no sampled mean; it is not a zero-valued "
                 "recommendation. Null target can describe a self/all/utility "
                 "identity without deriving an action description.</p>")
    for index, action in enumerate(record["legal_actions"]):
        document.add(f'<article id="alternative-{index}"><h3>Alternative {index}</h3>')
        _report_references(document, action, state)
        _facts(document, [
            ("Saved sampling status", action["status"]),
            ("Visits", action["visits"]),
            ("Raw shaped-reward sum", action["value_sum"]),
            ("Mean shaped reward", action["mean_shaped_reward"]),
        ])
        document.add("</article>")
    _fragment(document, record["legal_actions"], "/legal_actions",
              "Complete ordered alternatives and raw statistics")
    document.add('</section><section id="ranking"><h2>Ranking and recommendation</h2>'
                 "<p>Ranking retains reported order. It is not sorted or endorsed "
                 "by this reader. A Pass object has both indices null and its saved "
                 "label. It differs from a null recommendation, which means no "
                 "recommendation was recorded.</p>")
    _facts(document, [("Ordered raw ranking", record["ranking"])])
    recommendation = record["recommendation"]
    if recommendation is None:
        document.add("<p>No recorded recommendation: <code>null</code>.</p>")
    else:
        document.add("<h3>Reported recommendation object</h3>")
        _report_references(document, recommendation, state)
    _fragment(document, record["ranking"], "/ranking", "Complete ordered ranking")
    _fragment(document, recommendation, "/recommendation",
              "Complete recommendation object or null")
    document.add('</section><section id="work"><h2>Reported work and value meaning</h2>'
                 "<p>Counts, stopping reasons and elapsed time are saved "
                 "observations, not proof of execution or a resource guarantee. "
                 "Only their elementary consistency is admitted. Shaped simulator "
                 "rewards are not calibrated win probabilities.</p>")
    _facts(document, [
        ("Saved status", record["status"]),
        ("Saved search-performed claim", record["search_performed"]),
        ("Requested simulations", record["configuration"]["max_sims"]),
        ("Reported simulations", record["work"]["simulations"]),
        ("Reported transitions", record["work"]["transitions"]),
        ("Unused transition allowance", record["work"]["unused_transitions"]),
        ("Ordered stopping reasons", record["work"]["stop_reasons"]),
        ("Reported elapsed seconds", record["elapsed_seconds"]),
        ("Saved value explanation", record["value_semantics"]),
    ])
    if record["status"] == "no_work":
        document.add("<p>Zero requested simulations: all alternatives are unvisited, "
                     "ranking is empty and the recommendation is null.</p>")
    for name, title in (
        ("configuration", "Complete reported fresh configuration"),
        ("work", "Complete reported work"),
        ("elapsed_seconds", "Complete elapsed observation"),
        ("value_semantics", "Complete saved value explanation"),
    ):
        _fragment(document, record[name], f"/{name}", title)
    document.add('</section><section id="provenance"><h2>Saved provenance roles</h2>'
                 "<p>Stored recording provenance includes content, scenario, "
                 "configuration, episode.py implementation and environment RNG "
                 "checkpoint digests. Report-producer provenance identifies "
                 "decide_episode.py. These runtime labels, comparison names, "
                 "hashes and equality booleans are saved claims. None is observed "
                 "or authenticated here. RNG digests are not restorable states.</p>")
    _fragment(document, record["stored_provenance"], "/stored_provenance",
              "Complete recording provenance, all five branches")
    _fragment(document, record["implementation"], "/implementation",
              "Complete saved report-producer implementation and runtime")
    _fragment(document, record["identity_comparisons"], "/identity_comparisons",
              "Complete saved equality claims and distinct entrypoint roles")
    if record["schema_version"] == 2:
        document.add("<h3>Explicit selection and derivation</h3><p>Schema 2 admits "
                     "the declared mean/visits or visits/mean ordering using the "
                     "saved root encounter order for complete ties. This is "
                     "representation consistency, not policy endorsement. "
                     "A stability extraction performs no new search. Its "
                     "search-performed flag and counters describe the original "
                     "cell, including when the containing sweep was incomplete.</p>")
        for name in sorted(V2_FIELDS):
            _fragment(document, record[name], f"/{name}",
                      "Complete saved " + name.replace("_", " "))
    document.add("</section><footer><p>Body typography uses local Inter when its "
                 "declared faces are available, with Arial and the browser's "
                 "sans-serif fallback otherwise. JSON intentionally uses monospace. "
                 "No font is bundled or downloaded. Screen appearance is fixed "
                 "for this document. Print uses Clair.</p><p>Pinned Clair/Obscur "
                 "roles, MIT. Revision " + PRESENTATION_SOURCE["revision"]
                 + ". Original normalized token SHA-256 "
                 + PRESENTATION_SOURCE["sha256"]
                 + ".</p></footer></main></body></html>")
    return document.finish()


def decision_inspection_html(record_path: Path, *, appearance: str = "obscur") -> bytes:
    """Read one saved decision report and return passive HTML without file writes."""
    if not isinstance(appearance, str) or appearance not in THEMES:
        raise records.EpisodeInputError("appearance: choose obscur or clair")
    captured = records._read(record_path, "decision report", records.RECORD_BYTES)
    record = validate_decision_report(records._parse(
        captured, "decision report", 200_000, 10**300))
    try:
        return _render_decision(record, captured, appearance)
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise InspectionRuntimeError(
            "admitted decision report cannot be rendered") from exc


# Pair mode adds aggregate admission and composition without changing old renderers.
PAIR_VALUE_LIMIT = 200_000
_PAIR_GROUPS = (
    ("pair-inputs", "Captured reports and saved status",
     ("format", "schema_version", "status", "search_performed", "source_record")),
    ("pair-state", "Selected pre-action boundaries", ("selection", "selected_state")),
    ("pair-configuration", "Declared configuration and value meaning",
     ("configuration", "value_semantics")),
    ("pair-provenance", "Retained action and saved provenance",
     ("stored_action", "stored_provenance", "implementation", "identity_comparisons")),
    ("pair-work", "Reported work", ("work", "elapsed_seconds")),
    ("pair-choices", "Reported alternatives and recommendations",
     ("legal_actions", "ranking", "recommendation")),
)


def _pair_capture(path: Path, role: str, limit: int) -> tuple[dict, bytes]:
    captured = records._read(path, role, limit)
    parsed = records._parse(captured, role, 200_000, 10**300)
    try:
        return validate_decision_report(parsed), captured
    except records.EpisodeInputError as exc:
        raise records.EpisodeInputError(f"{role}: {exc}") from exc


def _pair_values(left: Any, right: Any) -> None:
    # Count admitted roots separately, without inventing another container level.
    pending: list[Any] = [right, left]
    visited = 0
    while pending:
        value = pending.pop()
        visited += 1
        if visited > PAIR_VALUE_LIMIT:
            raise records.EpisodeInputError(
                f"paired decision reports: exceeds {PAIR_VALUE_LIMIT} aggregate values")
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


def _pair_alignment(left: dict, right: dict) -> list[str]:
    failed = [
        "/" + name for name in ("selected_state", "value_semantics")
        if records.canonical(left[name]) != records.canonical(right[name])
    ]
    for name in ("method", "horizon_rounds"):
        if (records.canonical(left["configuration"][name])
                != records.canonical(right["configuration"][name])):
            failed.append("/configuration/" + name)
    return failed


def _pair_branch(document: _Document, name: str, difference: str | None,
                 left: dict, right: dict) -> None:
    status = "same" if difference is None else "different"
    location = "" if difference is None else difference
    document.add(
        f'<article id="comparison-{name}" data-comparison-field="{name}" '
        f'data-comparison-status="{status}" '
        f'data-first-difference="{escape(location, quote=True)}">'
        f"<h3>{name.replace('_', ' ').capitalize()}</h3>")
    _facts(document, [
        ("Typed branch comparison", status),
        ("First differing report pointer", difference),
    ])
    for side, record in (("left", left), ("right", right)):
        title = side.capitalize()
        document.add(f"<h4>{title}</h4>")
        if name == "selected_state":
            _boundary(document, record[name])
        elif name == "stored_action":
            _report_references(document, record[name], record["selected_state"])
        _fragment(document, record[name], f"/{side}/{name}",
                  f"{title}: complete {name.replace('_', ' ')}")
    document.add("</article>")


def _pair_choice(document: _Document, side: str, row: dict | None,
                 state: dict) -> None:
    document.add(f"<h4>{side}</h4>")
    if row is None:
        document.add("<p>Absent from this report. No statistic is supplied.</p>")
        return
    _report_references(document, row, state)
    _facts(document, [
        ("Saved sampling status", row["status"]),
        ("Visits", row["visits"]),
        ("Raw shaped-reward sum", row["value_sum"]),
        ("Mean shaped reward", row["mean_shaped_reward"]),
    ])
    if row["status"] == "unvisited":
        document.add("<p>Unvisited: no sampled mean. This is not a zero-valued "
                     "recommendation.</p>")


def _pair_choices(document: _Document, left: dict, right: dict,
                  failed: list[str]) -> None:
    available = not failed
    document.add('<div data-choice-alignment="'
                 + ("available" if available else "unavailable") + '">')
    if available:
        document.add(
            "<h3>Indexed alignment available under saved claims</h3>"
            "<p>Both reports declare the same complete selected state, literal "
            "value semantics, method and horizon. This permits raw index "
            "correlation, not authentication, legality or a controlled experiment. "
            "Different seeds, work allowances and counts remain visible. No "
            "cause, score improvement or probability is inferred.</p>")
        rows = [
            {(row["card_idx"], row["target_idx"]): row
             for row in record["legal_actions"]}
            for record in (left, right)
        ]
        identities = list(rows[0])
        identities.extend(identity for identity in rows[1] if identity not in rows[0])
        for index, identity in enumerate(identities):
            document.add(f'<article data-indexed-comparison="{index}">'
                         f"<h3>Raw indexed choice {index}</h3>")
            _facts(document, [
                ("Raw index pair [card_idx, target_idx]", list(identity))])
            _pair_choice(document, "Left", rows[0].get(identity),
                         left["selected_state"])
            _pair_choice(document, "Right", rows[1].get(identity),
                         right["selected_state"])
            document.add("</article>")
    else:
        document.add(
            "<h3>Indexed alignment unavailable</h3>"
            "<p>A required declared condition differs. The ordered alternatives "
            "are shown separately, with references into each report's own state. "
            "No shared statistical rows or numerical deltas are supplied.</p>")
        _facts(document, [("Failed alignment conditions", failed)])
        for side, record in (("Left", left), ("Right", right)):
            document.add(f"<h3>{side}: separate ordered alternatives</h3>")
            for index, row in enumerate(record["legal_actions"]):
                document.add(
                    f'<article data-separate-alternative="{side.lower()}-{index}">'
                    f"<h4>{side} alternative {index}</h4>")
                _pair_choice(document, side, row, record["selected_state"])
                document.add("</article>")
    document.add(
        "<p>Labels are literal and can differ for one raw identity. A Pass object "
        "has two null indices. A null recommendation records no recommendation. "
        "Missing alternatives, unvisited rows and nullable means remain distinct. "
        "Ranking retains each report's supplied order and is not endorsed.</p></div>")


def _render_pair(left: dict, right: dict, left_bytes: bytes, right_bytes: bytes,
                 appearance: str, differences: dict[str, str | None]) -> bytes:
    document = _Document()
    document.add('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width,initial-scale=1">'
                 "<title>Saved decision report comparison</title><style>"
                 + _css(appearance)
                 + 'nav[aria-label="Comparison sections"] a{min-width:0;'
                 'max-width:100%;overflow-wrap:anywhere}'
                 + "</style></head><body><main>")
    document.add(
        '<header id="overview"><h1>Saved decision report comparison</h1>'
        "<p><strong>Inputs and declared meaning before reported statistics.</strong> "
        "This passive reader admits two saved representations. It does not "
        "establish that search occurred, choices are legal or complete, counters "
        "are honest or values are accurate. No state reconstruction, environment, "
        "replay, search or RNG runs here.</p>"
        "<p><em>Recording, report-producer and actual passive capture are separate "
        "roles.</em> Matching hashes or fields establish representation agreement, "
        "not origin authentication or policy quality.</p></header>")
    _facts(document, [
        ("Left captured bytes", len(left_bytes)),
        ("Left captured SHA-256", hashlib.sha256(left_bytes).hexdigest()),
        ("Right captured bytes", len(right_bytes)),
        ("Right captured SHA-256", hashlib.sha256(right_bytes).hexdigest()),
        ("Screen edition", appearance),
    ])
    document.add(
        "<p>Left and Right were each captured once. These are independent reads, "
        "not a simultaneous snapshot, even when both paths name the same file. "
        "Caller paths and filenames are omitted. Captured hashes cover lexical "
        "bytes. Complete fragments preserve parsed types and values, not original "
        "whitespace, object key order or numeric spelling.</p>"
        '<nav aria-label="Comparison sections"><a href="#overview">Overview</a>')
    for anchor, title, _ in _PAIR_GROUPS:
        document.add(f'<a href="#{anchor}">{title}</a>')
    document.add("</nav>")
    failed = _pair_alignment(left, right)
    for anchor, title, names in _PAIR_GROUPS:
        document.add(f'<section id="{anchor}"><h2>{title}</h2>')
        if anchor == "pair-state":
            document.add(
                "<p>Each selection claims an original episode pre-action boundary "
                "after refill. Its /steps/N/state pointer is plain saved text, not "
                "an array in either report or a resource opened here. Hand and "
                "enemy slots stay ordered, including duplicates and dead entries. "
                "Missing indexed entries stay unresolved.</p>")
        elif anchor == "pair-configuration":
            document.add(
                "<p>Configuration and the literal saved reward explanation are "
                "compared before choices. Shaped rewards are not calibrated win "
                "probabilities. Different allowances or seeds prevent causal "
                "and equal-budget conclusions.</p>")
            if left["schema_version"] == 2 or right["schema_version"] == 2:
                document.add("<p>Coefficient changes rerun search. A visits/mean "
                             "selector can rerank the same captured statistics "
                             "without search. Different coefficients or selectors "
                             "remain declared differences; neither indicates "
                             "stronger decisions or equivalent trajectories. "
                             "Legacy schema 1 retains coefficient 1.2 and the "
                             "existing mean-first report meaning.</p>")
        elif anchor == "pair-provenance":
            document.add(
                "<p>The retained old action is distinct from the current saved "
                "recommendation. Original episode identities, recording/runtime "
                "maps, report-producer identities and equality booleans are "
                "unauthenticated saved claims. Names and hashes are plain text "
                "and are never opened. RNG digests are not restored states.</p>")
        elif anchor == "pair-work":
            document.add(
                "<p>Reported counts, stopping reasons and elapsed time are "
                "admitted for elementary consistency. They do not prove "
                "execution, equal budgets, speed or value accuracy.</p>")
        for name in names:
            _pair_branch(document, name, differences[name], left, right)
        if anchor == "pair-choices":
            _pair_choices(document, left, right, failed)
        document.add("</section>")
    if left["schema_version"] == 2 or right["schema_version"] == 2:
        document.add('<section id="pair-selection"><h2>Selection and extraction</h2>')
        for side, report in (("left", left), ("right", right)):
            document.add(f"<h3>{side.capitalize()}</h3>")
            if report["schema_version"] == 1:
                document.add("<p>Schema 1 has no encounter-order or derivation "
                             "fields.</p>")
            else:
                for name in sorted(V2_FIELDS):
                    _fragment(document, report[name], f"/{side}/{name}",
                              side.capitalize() + ": complete " +
                              name.replace("_", " "))
        document.add("</section>")
    document.add(
        "<footer><p>Body typography uses local Inter when its declared faces are "
        "available, with Arial and the browser's sans-serif fallback otherwise. "
        "JSON intentionally uses monospace. No font is bundled or downloaded. "
        "Screen appearance is fixed for this document. Print uses Clair.</p>"
        "<p>Pinned Clair/Obscur roles, MIT. Revision "
        + PRESENTATION_SOURCE["revision"] + ". Original normalized token SHA-256 "
        + PRESENTATION_SOURCE["sha256"] + ".</p></footer></main></body></html>")
    return document.finish()


def decision_comparison_html(left: Path, right: Path, *,
                             appearance: str = "obscur") -> bytes:
    """Capture two decision reports and return passive, input-first comparison HTML."""
    if not isinstance(appearance, str) or appearance not in THEMES:
        raise records.EpisodeInputError("appearance: choose obscur or clair")
    left_record, left_bytes = _pair_capture(left, "Left decision report",
                                           records.RECORD_BYTES)
    right_record, right_bytes = _pair_capture(
        right, "Right decision report", records.RECORD_BYTES - len(left_bytes))
    _pair_values(left_record, right_record)
    try:
        differences = {
            name: records.first_difference(left_record[name], right_record[name],
                                           "/" + name)
            for name in DECISION_FIELDS
        }
        return _render_pair(left_record, right_record, left_bytes, right_bytes,
                            appearance, differences)
    except records.EpisodeRuntimeError as exc:
        raise InspectionRuntimeError(
            f"admitted decision comparison cannot be compared: {exc}") from exc
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise InspectionRuntimeError(
            "admitted decision comparison cannot be rendered") from exc
