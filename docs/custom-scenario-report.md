# Report a decision from custom content

The checkout demo can load your card and scenario JSON and emit a saved decision
report. Use the existing `game.loader` input model. The engine wheel contains only
`engine`; this command belongs to the worked example in the checkout.

```console
python demo.py trial --cards C:/work/cards.json --scenarios C:/work/scenarios.json --scenario-seed 11 --seed 19 --horizon 2 --sims 16 --json
```

Both paths are required when supplying custom content. The positional name selects
one entry from the scenarios file. Omitting the paths uses the built-in content,
with `boss` as the default. Omitting `--json` retains the usual text display.
Unknown scenarios and malformed content are usage errors before search starts.

## Small input files

Save this as your cards file:

```json
{
  "cards": [
    {"name": "Pulse", "element": "ember", "type": "damage",
     "pip_cost": 0, "accuracy": 0.9, "damage_min": 40, "damage_max": 70},
    {"name": "Focus", "element": "neutral", "type": "blade", "modifier": 0.3}
  ]
}
```

Save this as your scenarios file:

```json
{
  "scenarios": {
    "trial": {
      "player": {"name": "Caller", "element": "ember", "hp": 700},
      "deck": ["Pulse", "Focus"],
      "enemies": [
        {"name": "Target", "element": "frost", "hp": 600,
         "is_boss": true, "rules": [{"type": "enrage_below_half", "blade": 0.2}]}
      ]
    }
  }
}
```

The loader deals seven initial cards from the ordered deck with
`--scenario-seed`, default 7. `--seed`, also default 7, independently seeds the
search or one-round sampling. The existing card fields, combatant fields and two
registered rule types, `punish_traps` and `enrage_below_half`, are supported.
See [cards.json](../data/cards.json), [scenarios.json](../data/scenarios.json) and
[game/loader.py](../game/loader.py) for the existing examples and validation.
These files do not import arbitrary Python rules or describe saved mid-round
states. Nonfinite JSON numbers and wrong container shapes are rejected.

## Retain and read the report

`--json` prints one object without the text table. Its format is
`mcts-decision-report`, schema version 1. Redirect stdout to retain it. On shells
that transform redirected text, a small Python consumer can save explicit UTF-8:

```python
import json
import os
import subprocess
import sys
from pathlib import Path

result = subprocess.run(
    [sys.executable, "demo.py", "trial", "--cards", "C:/work/cards.json",
     "--scenarios", "C:/work/scenarios.json", "--sims", "16", "--json"],
    check=True, capture_output=True, text=True, encoding="utf-8",
    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
)
report = json.loads(result.stdout)
Path("decision.json").write_text(result.stdout, encoding="utf-8")
print(report["recommendation"])
```

The report includes the complete modeled initial state and ordered deck, effective
configuration, separate scenario/search seeds, captured content SHA-256 and byte
counts, observed source hashes, runtime and package metadata, actual work and raw
accumulated action values. Input paths are excluded. Content hashes identify the
same captured bytes given to the existing loaders, even if the original files
change afterward. The consumer never rewrites your input files.

The `implementation` hashes describe observed example and imported engine files.
`distribution_version` is null if package metadata is unavailable.
`distribution_matches_import` says whether that distribution's engine directory
matches the imported package. `engine_import_kind` distinguishes source from
site-packages. These observations do not authenticate code or prove Git origin.
Running an external copy of `demo.py` and `game/` requires a separately installed
engine. The wheel does not install this demo, `game/` or the JSON content.

Every `legal_actions` row has a zero-based `card_idx` and `target_idx`, plus a
label. A null card index means Pass. A null target index means no enemy target,
including self-targeted and area actions. Duplicate labels may refer to distinct
hand slots or enemies, so use the index pair as identity. `ranking` preserves the
existing policy's sampled order, and `recommendation` identifies its first row.

For MCTS, `visits` and `value_sum` are the raw root statistics. An `unvisited`
legal option has zero visits, zero sum and a null `mean_shaped_reward`. It has no
estimated mean. One-round mode uses `samples` rather than MCTS visits:

```console
python demo.py trial --cards C:/work/cards.json --scenarios C:/work/scenarios.json --one-round-samples 2 --seed 19 --json
```

Both methods use the existing simulator, with different terminal rewards. MCTS
scores a terminal win as `1 - 0.045 * min(6, depth)`, favoring earlier wins.
It scores a terminal loss as `0.15 * min(depth, h) / h`, where
`h = max(1, horizon_rounds)`, giving a small survival reward for later losses.
Here `depth` counts simulated rounds from the root. One-round sampling uses
terminal win 1 and loss 0. Both use the existing HP/setup heuristic for ongoing
horizon states. The means are shaped rewards, not calibrated win probabilities.
One-round sampling compares complete equal-sample sweeps over legal actions and
uses no search tree. The report preserves each method's raw totals and ranking.

## Work and reproducibility

`--sims` disables clock stopping, including an explicitly supplied clock option.
The report keeps `requested_budget_ms` and reports the effective
`time_budget_ms` as null in that mode. `--sims 0` produces an empty ranking and
null recommendation while preserving unvisited legal choices. Timed searches
use 800 ms by default; their actual counts depend on the machine. Elapsed seconds
are observations, not a deadline guarantee.

With unchanged code/runtime/content/configuration and both seeds, fixed work
repeats the modeled state and decision evidence. Elapsed time still varies. This
does not establish serial/parallel equivalence or independent mathematical
correctness. A report is a record of one decision. This command does not import,
replay or independently recompute saved reports, and it does not record episodes.
