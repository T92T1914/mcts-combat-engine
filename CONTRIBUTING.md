# Contributing to MCTS Combat Engine

I welcome focused fixes, clearer examples and results that challenge an assumption in the project. If something looks wrong, I would rather have a small case I can run than a broad claim that it is broken.

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

Check the existing issues first. Include the revision, Python version, operating system, command, expected behavior and actual output. For a numerical issue, include the smallest input that demonstrates it. Remove credentials and private data from logs before posting.

Keep a pull request focused on one problem. Explain what changes for someone using the project, why the approach fits and which checks you ran. Add a regression test when it captures a real failure. Documentation changes should be checked against the current code and examples.

## Evidence and scope

Use the same game seeds, search budget and scenarios when comparing policies. Record the search seed and any safety time cap. Include results that get worse. A mean shaped reward is not a win probability, and a larger simulation count is not evidence of improved decisions by itself.

Useful next work includes a stronger baseline policy, results across several search seeds and a measured comparison of worker counts. Keep action identity and move legality intact when exploring these changes.

## Writing

Use plain language and concrete examples. Avoid em dashes and unnecessary hyphens in authored prose. Preserve the exact spelling of code, commands, paths, package names, links and quoted evidence. Claims about performance should link to measurements and say what was actually tested.

Be respectful when discussing a change. Questions and disagreements are welcome; keep them about the work.
