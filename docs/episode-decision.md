# A fresh decision from a saved episode state

Select one pre-action step from a saved episode and ask the current engine for a
new decision. The command uses the saved hand positions, enemy positions,
resources, modifiers, damage-over-time and registered rules. It needs no
original cards or scenarios files and does not replay the earlier rounds.

```text
python decide_episode.py episode.json --step 1 --seed 19 --sims 8 --horizon 2
```

`--step` is required and zero-based. Step 1 means `/steps/1/state`, after that
step's refill and before its stored action. Initial and final states cannot be
selected. The hand is not refilled during search. The stored deck remains
provenance, not a source of new cards for this decision.

## Run from a checkout or a copied example

A checkout contains the entry, `game/` helpers and `engine/`. Run the command
above with Python 3.11 or later. The engine uses the standard library.

For an installed engine, copy the committed `decide_episode.py` and the complete
committed `game/` directory together into an example directory. The wheel
contains only `engine`, so copying just the entry is insufficient. Use helpers
from the same source revision as the entry. Do not copy `engine/` into that
example, since it would shadow the installed package.

For example, in PowerShell from the source directory:

```powershell
New-Item -ItemType Directory -Path episode-example
Copy-Item .\decide_episode.py .\episode-example\decide_episode.py
Copy-Item .\game .\episode-example\game -Recurse
python -m venv episode-environment
.\episode-environment\Scripts\python.exe -m pip install .
```

This installs the engine from the current source directory. An existing engine
installation can also be used when its observed code identity is acceptable to
the caller. Put an existing episode JSON beside the copied example or pass its path. From
an unrelated working directory, invoke that environment's Python with the
copied entry's path. No `PYTHONPATH`, original content, `demo.py`, `episode.py`
or scenario factory is needed. The reported imported engine and adjacent helper
hashes identify the files actually observed. A version string alone does not
prove that two installations contain equal code.

## Controls and saved data

| Option | Default | Accepted values |
| --- | ---: | --- |
| `--step` | Required | Existing step 0..29 |
| `--seed` | 7 | Signed 64-bit integer |
| `--sims` | 16 | Integer 0..64 |
| `--horizon` | 4 | Integer 1..8 |

Programmatic callers use
`game.episode_decision.episode_decision(Path(...), step=1, seed=19, sims=8, horizon=2)`.
Booleans are not accepted as integer arguments.

The command captures the input once, with an 8 MiB limit, then uses the existing
strict episode parser and complete schema validator. It rejects duplicate JSON
keys, nonfinite numbers and unsupported shapes. Selected cards also pass the
current live card validator. Resources, active effects and registered rules
must reconstruct completely. A normalized comparison preserves numeric types,
nulls, ordered lists, duplicate hand slots and original enemy slots, including
dead enemies. Stored card names do not replace indexed identities.

A terminal selected state is an input error because no decision remains.
`--sims 0` reports every current legal alternative as unvisited, with no ranking
or recommendation. It constructs no search or RNG and runs no transition.

Positive work makes one serial search with a newly seeded RNG, no priors, no
clock limit and a transition allowance of `sims * horizon`, at most 512 simulated
rounds. These controls bound work counts, not wall time, memory, accuracy or
decision quality. The search leaves the reconstructed root unchanged.

## Read the JSON report

The report has format `mcts-episode-decision-report`, schema version 1.

- `source_record` identifies the one captured byte buffer by length and SHA-256.
- `selection` gives the step, round and exact selected-state pointer.
- `selected_state` contains the complete current reconstructed state.
- `stored_action` and `stored_provenance` preserve the saved action, content,
  scenario/deck, recording configuration, implementation and RNG declarations.
- `configuration` describes the fresh search. `work` records actual simulations,
  transitions, unused allowance and stop reasons.
- `legal_actions` shows every current indexed choice in legal order, including
  unvisited alternatives. Sampled rows include visits, raw value sums and means.
- `ranking` and `recommendation` preserve the current engine's sampled ordering.
- `implementation` observes current engine, complete game helpers, entry and
  runtime. `identity_comparisons` separates engine-file, example-file and
  runtime-field equality and names the different entrypoint roles.

The stored action is retained data. This command neither executes it nor
establishes its original legality, label accuracy or choice quality. Current
labels come from the selected state and current legal actions. Matching hashes
mean observed byte equality, not authenticated origin.

The recording used a continuously advanced search RNG. A fresh seed, even the
same number, starts a new stream and does not reproduce that later recording
decision. Environment RNG digests cannot restore RNG state. Stored code or
runtime differences do not prevent a fresh decision when the state remains
fully supported, but the differences remain visible in the report.

Identity reads admit at most 128 source or extension files, 4 MiB per file and
16 MiB total. These are observed-file reading limits. Directory enumeration and
its memory use are not covered by a separate traversal limit.

Means are the existing shaped simulator rewards, including depth-shaped terminal
scores and the ongoing HP/setup heuristic. They are not calibrated win
probabilities or proof of an optimum. Exact agreement with a direct current
engine call is consistency within that engine, not an independent mathematical
oracle. Elapsed search time is an observation and does not stop the search.

## Save output and understand errors

The command buffers and checks the complete finite JSON before writing binary
stdout. Its 8 MiB output limit includes the final LF. No progress text shares
stdout. Keep stderr separate when saving a report.

In PowerShell 7.4 or later, native stdout redirection preserves the emitted
bytes. Use a fresh output filename because `>` overwrites an existing file:

```powershell
python decide_episode.py episode.json --step 1 --sims 8 --horizon 2 > fresh-decision.json
```

Older Windows PowerShell may transcode native output. Combining stderr and
stdout also changes the stream behavior. See the
[Microsoft redirection documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection?view=powershell-7.5).

| Exit | Meaning |
| --- | --- |
| 0 | Complete decision or truthful `no_work` report |
| 2 | Argument, record, selected-state or terminal refusal, no JSON |
| 1 | Search, identity, report or output failure |
| 130 | Interrupted operation |

Input errors name the selected location where applicable. Current code identity
is observed before work and rechecked before successful return. Unsupported
representations refuse rather than drop fields. Some schema-admitted fabricated
states can still cause an arithmetic failure in the unchanged engine. That is a
contextual runtime error, not a silent model repair or a reachability proof.

Failures before output leave stdout empty. A sink failure while writing or
flushing may leave partial bytes, which are not a valid successful report. The
entry retires a failed buffered sink before interpreter shutdown can retry it.
The original input is never rewritten. A caller changing it after capture does
not change the captured-buffer identity, and no immutability guarantee against
other processes is claimed.
