# Working on MCTS Combat Engine

A useful change here makes the search easier to reason about, catches a wrong decision, or gives it a fairer comparison. I want the small state that explains a failure alongside any larger benchmark.

## Start locally

Use Python 3.11 or later and run these commands from the repository root. A virtual environment keeps the development dependencies separate from your other projects.

```sh
python -m venv .venv
```

Activate it with `.venv\Scripts\Activate.ps1` in PowerShell, or `source .venv/bin/activate` on macOS or Linux. Then install what this project needs:

```sh
python -m pip install -e ".[dev]"
```

## Check a change

```sh
python -m unittest discover -s tests
ruff check .
mypy
```

Start with [search](engine/mcts.py), [action rules](engine/actions.py) and the [design decisions](docs/design-decisions.md). The [benchmark report](docs/benchmark-results.md) includes the measured regression as well as the gains.

## Report a bug or propose a change

Include the smallest failing state, command, revision and expected action. Removing a card changes list indexes, but an edge must still identify the same card. Legal moves can also change between sampled outcomes. A search improvement cannot depend on the simulator silently turning an invalid action into a pass.

For an algorithm change, explain how the value is backed up and which actions were available. Start with [the action identity regressions](tests/test_action_identity.py). For a benchmark change, save the comparison and its source revision so someone else can inspect the same budget.

## Evidence and scope

Use the same game seeds, search budget and scenarios when comparing policies. Record the search seed and any safety time cap. Include results that get worse. A mean shaped reward is not a win probability, and a larger simulation count is not evidence of improved decisions by itself.

Useful next work includes a stronger baseline policy, results across several search seeds and a measured comparison of worker counts. Keep action identity and move legality intact when exploring these changes.

## Development container and public site

Open this repository in Codespaces or use VS Code Dev Containers. The container uses Python 3.11 and installs the project into `.venv` during setup. Its image is pinned by digest. The `Project access` workflow builds that same environment and runs `.devcontainer/smoke.sh`. Runtime dependencies still follow the project configuration. Codespaces uses the creating account's compute and storage allowance.

Run `python tools/build_site.py` to assemble the public page in `_site`, then `python -m http.server 8080 --directory _site` to preview it. The builder copies only the listed example files. The page reads saved evidence; it does not silently rerun the experiment or claim current results. Pages deploys from `main` after the site and development environment checks pass.
