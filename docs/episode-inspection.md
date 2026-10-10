# Read saved episodes and decision reports as HTML

The inspection command turns a saved episode or an explicitly selected decision
report into a self-contained reading artifact. For episodes, follow the stored
decisions, indexed hand and enemy entries, initial state and completion. Expand
the JSON sections for every admitted value, including
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
3. Choose a saved episode record or supported decision report. No copied
   `engine/`, `demo.py`, `data/` or original caller content is needed for this
   inspection journey.

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

## Read a saved decision report

Use the explicit report mode for a saved `mcts-episode-decision-report` schema 1
produced by the saved-state decision command:

```text
python inspect_episode.py fresh-decision.json --decision-report > decision.html
python inspect_episode.py fresh-decision.json --decision-report --appearance clair > decision-clair.html
```

The ordinary command still expects an episode record. The flag selects only the
saved decision format. Passing the wrong format is an input error, with no format
guessing or fallback. The reader does not open the original episode, reconstruct
the selected state, run search, check legality or observe the current runtime.

The top of the artifact separates two identities. The captured decision-report
byte count and SHA-256 are calculated from the bytes this reader captured once.
The original episode byte count and digest are claims retained from
`source_record`. They identify different files and do not authenticate either one.

The selection describes the original episode's state after refill and before its
recorded action. Its `/steps/N/state` pointer names that original episode boundary,
not an array inside the decision report. Read the selected hand in its stored
order, including all seven possible slots, and keep dead enemies in their original
slots. Action references use only this saved state. A supported index with no
corresponding saved entry stays visible as unresolved.

The retained old action comes from the original recording. Reported alternatives,
ranking and recommendation belong to the saved decision report. Labels are kept
literal, even when names repeat. A Pass object has null card and target indices,
with its saved label. A null recommendation means no recommendation was recorded.
A non-null card with a null target can represent a self/all/utility identity.
The reader derives no action description from these indices.

Every alternative retains its raw visits, shaped-reward sum and nullable mean.
Unvisited rows have zero visits and no mean. They are not recommendations valued
at zero. The recorded ranking stays in its supplied order. Shaped simulator
rewards are not calibrated win probabilities. Zero requested simulations produce
a no-work representation with all rows unvisited, zero counts, empty ranking and
null recommendation.

Report admission checks exact supported shapes and bounds, unique raw action
identities, the saved visits sum, sampled mean arithmetic, ranking membership and
the recommendation's first-row identity and label. Positive work counts must agree
with the declared simulation/transition allowance. No-work fields must agree with
each other. These elementary checks do not prove that search happened, counters
are honest, choices are legal or complete, or values are accurate.

Recording provenance contains all five retained branches: content, scenario and
deck, recording configuration, `episode.py` implementation and environment RNG
checkpoint digests. The report-producer implementation separately identifies
`decide_episode.py`. Saved runtime differences and equality booleans remain claims.
They are not recalculated by the passive reader. Environment RNG digests are not
states that this viewer restores.

Exactly eighteen expandable JSON fragments preserve all top-level report fields,
including both provenance roles, comparison maps, stopping reasons and elapsed
time. Arrays retain order. Integer, float, boolean and null kinds remain distinct,
and negative zero retains its round-trip representation. The reader does not
preserve original JSON whitespace or lexical number spelling. Filenames and hash
map entries are displayed as text without opening them.

Report mode shares the 8 MiB read-once input bound, sixteen container levels,
200,000 values and numeric magnitude up to `10**300`. It admits one to 57 reported
alternatives, zero to 57 ranking identities and at most 64 reported simulations.
These are representation bounds, not a new engine resource guarantee. Complete
HTML uses the same fixed editions, local fonts, escaping, 64 MiB output bound and
failure behavior described below.


## Explicit schema 2 decisions

`--decision-report` also admits schema 2. Its explicit coefficient, final-action
rule and captured root encounter order must agree with its ranking. Complete
ties preserve that encounter order. Schema 1 keeps its existing coefficient
1.2 and raw reported ranking admission. Neither version is authenticated or
endorsed by the reader.

Schema 2 fragments include complete encounter order and derivation. A stability
extraction retains the original cell's search/work declarations and separately
states `new_search_performed=false`. Its source sweep can be incomplete even
when the selected cell completed. See [the diagnostic guide](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-stability.md).
Mixed-version comparison retains each complete input, exposes configuration
differences and explains coefficient reruns versus same-stat selector changes.
It executes no additional search and makes no policy-quality inference.

## Compare two saved decision reports

Select pair mode explicitly:

```text
python inspect_episode.py left.json --decision-report --compare-report right.json > comparison.html
```

`--compare-report` requires `--decision-report`. Neither input is guessed to be an
episode. Both files must pass the same supported report validator. Existing
single-report and episode commands keep their output behavior.

For the complete [example kit](episode-example-kit.md), extract all files into a
fresh directory, then move that whole directory if needed. Keep both entries and
the complete `game/` together. Use the Python executable for your selected
installed engine. Do not add a local `engine/`. From an unrelated working
directory, supply two external report paths:

```powershell
& 'C:\work\engine-env\Scripts\python.exe' 'C:\work\moved-kit\inspect_episode.py' 'C:\records\left.json' --decision-report --compare-report 'C:\records\right.json' --appearance clair > comparison-clair.html 2> comparison-errors.txt
```

Substitute your paths and use fresh output names. PowerShell 7.4+ preserves native
stdout bytes. A POSIX shell also supports byte-preserving redirection. Older
Windows PowerShell can change the encoding. Keep stderr separate. Redirection
can create or overwrite its file even when the command fails. No Git, original
episode/content, checkout `PYTHONPATH` or matching saved runtime is needed.

Open the HTML anywhere without companion assets. It contains both reports' full
modeled data and saved runtime labels, so choose deliberately whether to share it.
The caller's filenames and paths are omitted.

Each role is captured once, including when both paths name the same file. These
are independent reads, not a simultaneous snapshot. Actual capture hashes
identify those bytes. Claimed original episode hashes and provenance remain
unauthenticated saved values.

The document shows selected state, declared configuration, reward meaning and
provenance before statistics. Each of eighteen branches has a typed same/different
result and its first differing report pointer. Thirty-six expandable fragments
retain both complete inputs, including integer/float distinctions, negative zero,
nulls and ordered lists. Parsed fragments do not preserve original whitespace or
number spelling.

Raw choice indices align only when the reports declare identical selected state,
literal value semantics, method and `horizon_rounds`. Otherwise lists remain
separate. References use each report's own stored slots, including duplicate,
dead and unresolved entries. Labels are literal. An absent row, an unvisited row,
a nullable mean, a Pass object and a null recommendation are distinct.

Matching declared conditions do not authenticate producers, recompute legality or
establish a controlled experiment. Different seeds, allowances and counts stay
visible. Saved shaped rewards are not win probabilities. No score improvement,
causal effect or policy quality is inferred.

Pair mode retains an aggregate 8 MiB captured-byte allowance and 200,000 values
across both inputs, sixteen container levels per input and 64 MiB total HTML.
Each input also retains its existing schema limits. Two individually valid files
can exceed the pair allowance. These are content bounds, not memory or timing
guarantees. Both admissions and complete rendering precede HTML stdout. Input
refusals exit 2, rendering/output failures 1 and interruption 130, with the same
sink and shell limitations described below.

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

Exit 0 means complete HTML, except that ordinary -h/--help prints usage without
reading an input. Usage, read and schema errors exit 2. Rendering,
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
