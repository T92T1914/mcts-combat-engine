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
