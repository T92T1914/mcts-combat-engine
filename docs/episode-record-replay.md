# Record an episode and replay its environment

`episode.py` retains a bounded sequence of decisions and complete simulator states.
Its replay command regenerates the environment using those recorded actions. It
does not rerun MCTS to choose them again.

This is a checkout example. The installed wheel contains only `engine/`, so keep
`episode.py`, `demo.py`, `game/` and `data/` together when copying the example.
The accepted single-decision `demo.py` command remains available.

## Record and retain the inputs

```powershell
python episode.py record duel --rounds 4 --sims 8 --horizon 2 > episode.json
python episode.py replay episode.json > replay-result.json
```

Custom input uses the same cards/scenarios format and registered rules as the
[decision report](custom-scenario-report.md), within the limits below.

```powershell
python episode.py record trial --cards cards.json --scenarios scenarios.json --environment-seed 7 --search-seed 11 --rounds 4 --sims 8 --horizon 2 > episode.json
python episode.py replay episode.json --cards cards.json --scenarios scenarios.json > replay-result.json
```

Both commands always emit JSON. There is no output-path or overwrite API. Shell
redirection controls the destination and may overwrite it, so choose a new name
when retaining an earlier episode. On Windows, use a shell that preserves native
stdout bytes, such as PowerShell 7.4 or later. Keep stderr separate when saving
the record. Combining stderr/stdout creates a text stream, and older Windows
PowerShell can re-encode redirected output. See Microsoft's
[redirection behavior](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection?view=powershell-7.5)
and [Windows PowerShell encoding](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_character_encoding?view=powershell-5.1).
The command itself writes canonical bytes directly to stdout, including one LF.
Replay requires UTF-8 input.

A record identifies the exact captured content bytes by SHA-256 and byte count.
It does not embed the caller's original files. Retain them unchanged. Custom
replay requires the same custom pair. Built-in replay reads current built-in
files. Changing whitespace in a content file changes its identity.

Defaults are scenario `boss`, environment seed 7, search seed 7, 30 rounds,
16 simulations per decision and horizon 4. Replay takes its scenario, seeds,
round cap and recording configuration from the record. Search options cannot
override them.

## What gets retained

A version 1 `mcts-episode-record` contains:

- captured content identity, scenario name/environment seed and ordered deck;
- complete initial state, including modeled defaults and effective rule parameters;
- observed implementation/runtime identity and recording configuration;
- ordered steps with a detached state after hand refill and before decision,
  round number and exact zero-based `card_idx`/`target_idx` plus label;
- complete final state, returned score, terminal result, completed rounds and
  terminal versus round-limit completion;
- environment RNG checkpoint digests after scenario creation and at completion.

Action labels may repeat. The index pair identifies the current hand card and
original enemy slot. Removing a card shifts later hand indices. Dead enemies
retain their slots. A played final card can leave six cards in the final hand,
while the next decision boundary refills to seven.

These snapshots are decision boundaries, not every individual random event.
The next boundary includes refill after the preceding round. The final state
captures the last round's outcome. Saved states and RNG checkpoints are never
imported into the simulator.

Recording uses one existing clockless serial MCTS owner with no priors and
exploration 1.2. Its separate search RNG is seeded once and continues across
decisions. The environment RNG first deals the initial hand, then continues
through refill and round outcomes. A separate policy RNG is supplied to the
runner, but the MCTS owner does not use it. No parallel workers or clock stopping
are used. Simulation and transition limits bound admitted work, not elapsed time.

## Replay checks and errors

Replay first validates the retained data and compares observed content/code/runtime
identity. It then constructs the scenario with the retained environment seed and
continues the same RNG stream. It checks each regenerated boundary, validates the
stored action against current legal choices, and returns that action through the
existing runner. Invalid actions fail before that round advances. They do not
silently become Pass.

Successful output has format `mcts-episode-replay-result`, status
`environment_replay_verified`, verified step count, current identities, the final
result and `search_recomputed: false`. Final verification includes full state,
score, terminal result, round count, completion reason and RNG checkpoint. A
terminal result on the last allowed round remains terminal. An ongoing round-limit
score is the existing heuristic, not a calibrated win probability.

Mismatches include a deterministic first relative JSON location, such as
`/steps/1/state/player/hp` or `/final/state/enemies/0/hp`. Objects are traversed by
sorted key, arrays by index. Missing entries identify their key/index. Keys escape
`~` as `~0` and `/` as `~1`, following JSON Pointer syntax. Object-key order is
irrelevant. Exact canonical comparison distinguishes integer, float and boolean
representations and adds no tolerance. Preserve numeric representations if
rewriting a record. Its captured record digest identifies the actual retained
bytes, including formatting.

| Exit | Meaning and output |
| --- | --- |
| 0 | One complete record or verified replay JSON object, written and flushed including LF |
| 2 | Argument/read/size/UTF-8/JSON/schema/content error, stderr diagnostic and empty stdout |
| 3 | Initial content or observed implementation incompatibility, JSON status `incompatible`, before scenario generation |
| 1 | First environment divergence, JSON status `mismatch`, or runtime/cleanup/output failure with stderr |
| 130 | Interrupted command, stderr diagnostic |

Success output is buffered until owner cleanup, identity reobservation and output
validation finish. A generated oversized/nonfinite record or code change after
admitted work is a runtime failure, not initial incompatibility. A failed or
interrupted recording does not emit a successful partial episode.

The command checks that its output stream accepted every JSON byte and the final
LF, then explicitly flushes before returning the record or replay status. An
incomplete write or refused write/flush returns 1; interruption during delivery
returns 130. Errors before output starts leave stdout empty. A delivery failure
can leave partial or complete bytes in a redirected file or pipe, so check the
exit status before using them. The command does not retry or remove those bytes.
Flush acceptance does not establish durable disk storage or atomic replacement.

Calling `main()` keeps the caller's output stream open. The executable retires a
failed buffered stdout before interpreter shutdown can retry it and replace the
intended failure status. Replay still requires matching implementation hashes,
including `episode.py`; an entry change makes a record from a different entry
incompatible (exit 3), before scenario work. Keep that record with its matching
source instead of rewriting its stored hashes.

## Supported bounds

| Boundary | Limit |
| --- | --- |
| Environment/search seeds | Signed 64-bit integers |
| Rounds / simulations per decision / horizon | 1..30 / 1..64 / 1..8 |
| Transitions per decision | Simulations multiplied by horizon, at most 512 |
| Each content file / retained or emitted record | 262144 / 8388608 bytes, output including LF |
| Cards / scenarios / deck entries / enemies | 1..128 / 1..16 / 1..128 / 1..8 per scenario |
| Registered rules | At most two total across a scenario's enemies |
| Names / optional scenario description | 1..128 / at most 2048 characters |
| Source integer combat values | Nonnegative, at most 1000000, with positive HP and punish damage |
| Source dot duration | 0..30, with paired fields required by the existing loader |
| Other source numeric values | Finite, absolute value at most 1000000, then existing loader constraints |
| JSON containers / parsed values | Depth 16, 20000 values per content file, 200000 per record |

The example accepts a narrower bounded input set than the general loader. It
rejects duplicate keys, booleans as numbers, nonfinite values, unknown fields and
unsupported rules. States retain complete dataclass fields. Snapshot modifier
lists are bounded to 128 entries each and dots to 256 per combatant. Record
numeric magnitudes cannot exceed 10^300. Steps cannot exceed the round cap and
must have contiguous indices. Arbitrary states, Python rules, callbacks and
mid-round imports are unsupported.

## Compatibility and evidence limits

Compatibility requires matching observed Python version/build/implementation,
machine/pointer width, cache tag, RNG version, platform and actual imported
engine/example hashes and distribution metadata. These hashes use observed raw
bytes. They do not authenticate executing code or establish Git provenance.
Code filenames are comparison labels, never paths loaded from the record.
Relocation is supported. Cross-version replay is not promised. A source checkout
and installed wheel can have different bytes/import metadata even with the same
package version, so record and replay within the same observed implementation.

Reading stored events displays them without verification. Environment replay
checks consistency under the same simulator. Stochastic decision recomputation
would run the policy again and is outside this command. Successful replay does
not prove that the original policy chose the actions, authenticate the artifact,
establish optimality or validate the model. An authored internally consistent
alternative episode can also replay successfully.

Consumer acceptance uses a retained actual command record and a separate replay
process with policy/search constructors and calls forbidden. Installed acceptance
copies the committed example outside the checkout without local `engine/`, proves
imports from the exact installed wheel, and records/replays there using caller
JSON outside the copy. Source checks and fixtures alone do not establish that
installed consumer result. No browser or native application is required.
