# Record, replay and inspect with the episode companion

The separate `episode-companion.zip` contains the existing example commands,
their complete `game/` helpers and default cards/scenarios. Extract the whole
companion into a fresh directory, then install the engine with Python and pip.
You do not need Git, a development checkout or the development extras. The
engine package still installs only `engine/`. The companion contains no engine
or wheel and does not change the existing saved-episode reader kit.

## Acquire both parts

Use Python 3.11 or later. These PowerShell examples use `C:\work` as an existing
parent directory. Choose your own paths. First download
[the companion](https://t92t1914.github.io/mcts-combat-engine/episode-companion.zip)
and [its checksum](https://t92t1914.github.io/mcts-combat-engine/episode-companion.zip.sha256).
Compare `Get-FileHash .\episode-companion.zip -Algorithm SHA256` with the
sidecar, then extract the complete ZIP to `C:\work\episode-companion`.
Create an environment and read the extracted manifest to install the engine
from the companion's source revision:

```powershell
python -m venv C:\work\engine-env
$sourceCommit = (Get-Content C:\work\episode-companion\manifest.json -Raw | ConvertFrom-Json).source_commit
& C:\work\engine-env\Scripts\python.exe -m pip install "https://github.com/T92T1914/mcts-combat-engine/archive/$sourceCommit.zip"
```

Pip downloads the source archive and builds the engine wheel in its temporary
isolated build environment. It obtains the packaging backend automatically.
This requires network access and ordinary pip build support, but no compiler,
Git or editable installation. It does not install `.[dev]` or the example files.
For an offline environment, obtain a matching engine wheel separately and use
`python -m pip install --no-index --no-deps PATH_TO_WHEEL` instead. A version
string alone does not establish matching code.

`manifest.json` records source, payload and separate reference engine identities.
Every payload file, including this guide, is literal committed source.

Keep `demo.py`, `episode.py`, the saved-record entries, `reference_episode.py`,
and the full `game/`, `reference/` and `data/` together. `demo.py` participates in implementation identity even when
you never run it. Move the whole directory when relocating the companion.
Do not add a local `engine/`, which would shadow the installed engine.

## Supply your own cards and scenario

Use separate JSON files following the included `data/cards.json` and
`data/scenarios.json` structures. A scenario names a deck of cards, player and
enemies. Supply both `--cards` and `--scenarios` when recording or replaying
custom content. Keep their exact bytes: replay checks their recorded hashes.
See [record and replay](episode-record-replay.md) for validation, the supported
card/rule schema, bounds and status meanings. A valid tiny custom pair is used
by the installed-consumer CI witness; the default files are also usable inputs.

## Complete one bounded journey

Run from any working directory using the installed Python and absolute entry
paths. PowerShell 7.4 or later preserves native stdout bytes in these examples.
Use fresh output filenames and keep stderr separate. Redirection can create or
overwrite a target even when the command fails. Check `$LASTEXITCODE` after
each command before treating its output as usable. POSIX byte redirection also
works. Older Windows PowerShell can change output encoding.

```powershell
$py = 'C:\work\engine-env\Scripts\python.exe'
$companion = 'C:\work\episode-companion'
& $py "$companion\episode.py" record YOUR_SCENARIO --cards C:\work\my-cards.json --scenarios C:\work\my-scenarios.json --rounds 3 --sims 2 --horizon 1 > C:\work\episode.json
& $py "$companion\episode.py" replay C:\work\episode.json --cards C:\work\my-cards.json --scenarios C:\work\my-scenarios.json > C:\work\replay.json
& $py "$companion\inspect_episode.py" C:\work\episode.json --appearance obscur > C:\work\episode.html
& $py "$companion\decide_episode.py" C:\work\episode.json --step 0 --seed 19 --sims 2 --horizon 1 > C:\work\decision-a.json
& $py "$companion\inspect_episode.py" C:\work\decision-a.json --decision-report --appearance obscur > C:\work\decision.html
& $py "$companion\decide_episode.py" C:\work\episode.json --step 0 --seed 23 --sims 2 --horizon 1 > C:\work\decision-b.json
& $py "$companion\inspect_episode.py" C:\work\decision-a.json --decision-report --compare-report C:\work\decision-b.json --appearance obscur > C:\work\comparison.html
```

Recording runs a new episode with fixed search work and a round bound. Replay
applies the saved actions and environment stream, with no new search. Passive
HTML inspection performs neither replay nor search. `decide_episode.py` is the
explicit fresh-search operation: it reads the existing pre-action `/steps/0/state`
and uses the newly supplied search seed and allowance. It does not refill the
hand or continue the recorded policy's random stream. Comparison reads two
saved reports without computing another decision. Open the completed HTML
files locally to inspect them.

## Agreement, differences and limits

Environment replay requires matching implementation, runtime labels and exact
original content. Source-checkout and installed-engine identities differ.
Historical files retain these rules and are never rewritten to make a replay
pass. A matching installation and literal companion may replay an older record
when all recorded identities agree; arbitrary cross-version compatibility is
not promised. Passive reading has its existing structural admission rules and
does not require the original custom content or matching runtime labels.

Record/replay keep their existing statuses: 0 for completed recording or
agreement, 1 for a valid replay mismatch or runtime/delivery failure, 2 for
invalid input, 3 for replay incompatibility, and 130 for interruption. The
reading and decision guides specify their own unchanged statuses. Complete
JSON output ends with LF and is flushed by its entry; shell redirection itself
does not preserve prior output files or make a result durable.

Fixed simulations and rounds bound declared work, not elapsed time or memory.
Fresh decision values are shaped sampled rewards, not win probabilities or
independent mathematical validation. Comparison explains eligibility and
differences in retained reports, including search settings, without promising
that one action improves on another. Hashes establish compared byte identity,
not authentication. Read [inspection](episode-inspection.md) and
[saved-state decisions](episode-decision.md) for complete admission and limits.

For maintainers, `python tools/build_episode_companion.py` generates the ZIP
and sidecar from a clean committed checkout using the reader kit's bounded
source capture and archive primitives. The existing site builder publishes
both distinct distributions. Output writes are not atomic as a pair; a failed
pair must not be published.

The same companion supports a [bounded saved-state stability diagnostic](episode-stability.md).
It repeats fixed-work decisions across admitted seeds and coefficients, then
extracts a constituent for this existing inspector and comparison. Included
baseline evidence and repeat commands preserve source identities. The engine's
default selector, rewards and coefficient remain unchanged.

The complete companion also includes an [independent one-round reference](episode-reference.md).
It prices a saved horizon-one decision, including an extracted stability cell,
and produces exact action expectations and score losses for passive inspection
and comparison. The default retains the original one/two-enemy subset.
`reference_episode.py --model three-enemy` explicitly selects the separately
identified exactly-three-enemy model. The reference guide includes a complete
bundled gauntlet recording, replay, calculation and passive comparison journey.
Saved reports retain their declared model, including historical version-1
reports. The probability law and cooperative limits are explicit. This addition
preserves the engine and separate reader kit.
