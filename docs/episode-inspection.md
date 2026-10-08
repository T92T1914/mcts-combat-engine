# Read a saved episode as HTML

The inspection command turns a saved episode into a self-contained reading
artifact. Follow the stored decisions, indexed hand and enemy entries, initial
state and completion. Expand the JSON sections for every admitted value, including
the ordered deck, modifiers, damage-over-time, rules, nullable fields, seeds,
configuration, runtime labels and file identities.

This is passive inspection. Schema admission does not authenticate the record,
verify stored runtime claims or prove which policy chose its actions. The command
constructs no environment or policy and performs no replay or search. Original
cards/scenario files and a matching recorded runtime are unnecessary.

## Set up the copied example

Python 3.11+ is required. From a checkout, run the top-level command directly.
For a copy outside the checkout:

1. In the supported checkout, run `python -m pip install .` with the selected Python
   environment, or use its existing accepted engine installation. Use the helpers
   from that same supported revision. This installs only the `engine` package.
2. Copy the committed `inspect_episode.py` and the complete committed `game/`
   directory together into an example directory. Keep their relative layout.
   `game/` and this command are examples, not members of the engine wheel.
3. Choose a saved record. No copied `engine/`, `demo.py`, `data/` or original caller
   content is needed for this inspection journey.

```text
python inspect_episode.py episode.json > episode.html
python inspect_episode.py episode.json --appearance clair > episode-clair.html
```

Use a fresh output filename. The shell can create or overwrite its target even
when the command fails. Keep stderr separate from HTML stdout. Save with
byte-preserving native redirection, such as PowerShell 7.4+ or a POSIX shell.
Older Windows PowerShell can transform native output into a different text
encoding. Microsoft's [redirection documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection)
explains the native-byte behavior and the effect of combining streams.

Open the resulting HTML with a browser. It can be moved with no companion assets.
The chosen artifact contains the record's modeled data and stored runtime labels.
Decide deliberately whether to share it.

## Read boundaries and action references

The initial state is the scenario-created state before the runner's first refill
and decision. Each numbered step shows its state after refill and before its own
recorded action. The final state follows the last action and round, without another
decision refill, or represents immediate terminal completion with zero steps.
It may contain six hand cards.

Action indices resolve against that same step's hand and original enemy slots.
Duplicate cards, shifted hand positions and dead enemy entries stay in order.
Null remains null. An index with no stored entry is shown as unresolved. The stored
label stays literal, with no new legality check or inferred action description.

Changes between consecutive step states can include the prior action, round
effects and the next refill. The report does not isolate an action's effect or
invent intermediate random events. Raw score and completion values remain stored
claims. A round-limit heuristic is not a calibrated win probability.

Every parsed JSON type and value appears in complete expandable fragments. Integers
remain exact, floats retain their JSON round-trip representation, and arrays keep
their order. Original JSON whitespace and lexical number spelling are not retained.
The input byte count and SHA-256 identify the exact captured bytes, not origin or
authenticity. The input is read once and never rewritten. Its caller filename and
path are omitted from the report.

## Appearance and limits

Obscur is the fixed default. `--appearance clair` changes only presentation. Print
uses Clair. The pinned Clair/Obscur roles come from revision
`7a57fe750ff50205a17e1d342106a0d3f2777159` under MIT. Body text uses local Inter
400, 600 and 700 with genuine italic faces when available, then Arial and the
browser's sans-serif fallback. JSON uses monospace. No font is bundled, installed
or downloaded, so another machine may use a fallback.

The existing record admission limits apply: 8 MiB input, 16 container levels,
200,000 values, numeric magnitude up to `10**300`, field-specific validation and at
most 30 recorded decisions. Complete HTML is buffered and must fit 64 MiB including
its final LF. Excess output is refused before writing. These are finite content
bounds, not memory or timing guarantees.

Exit 0 means complete HTML. Usage, read and schema errors exit 2. Rendering,
generated-size, resource and output failures exit 1. Interrupted generation exits
130. Diagnostics go to stderr. Failures before the final write leave HTML stdout
empty. A failing output sink can receive a prefix because a pipe write is not
atomic publication.

The artifact uses escaped text, fixed local navigation and native expandable
sections. It has no scripts, external resources, uploads or preference storage.
Stored hashes and filenames are plain text. Keyboard navigation and text enlargement
remain browser features. Inspection is separate from the supported
[environment replay](episode-record-replay.md), which checks recorded actions and
boundaries under compatible content and implementation. Neither capability
establishes model validity, optimality or policy strength.
