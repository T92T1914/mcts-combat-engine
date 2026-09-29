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

Keep policy randomness separate from environment outcomes. Record both seed
ranges and inspect the exported decision simulation counts for budget shortfalls.
The benchmark starts search fresh for each scenario, then retains its stream
across that scenario's games. A change in scenario order must not change a
completed fixed-budget result. Historical tables made with the earlier shared
stream remain historical evidence and should not be overwritten by a new run.

The [one-round comparison](docs/comparison-results.md) retains a frozen protocol,
per-game outcomes and separate work counts across several search seeds. Regenerate
its tables with `python tools/render_comparison.py`, or check them without writing
with `python tools/render_comparison.py --check`. Keep historical results intact
when collecting a new study. The separate
[transition allowance comparison](docs/transition-comparison-results.md)
records complete simulations and action
sweeps under a shared allowance. Its protocol was committed before outcomes.
Check its data and generated report with
`python tools/render_transition_comparison.py --check`. Keep time shortfalls,
unused remainders, terminal losses and unfinished games distinct. Equal transition
allowances do not establish equal elapsed work. A measured comparison of worker
counts remains separate work. Keep action identity and move legality intact.

The new [parallel fixed work contract](docs/parallel-fixed-work.md) divides total
allowances and preserves unknown work on a lost worker. Its bounded scaling
protocol is separate from the earlier complete game studies. Commit the tested
implementation and `docs/parallel-scaling-protocol.json` before executing
`tools/run_parallel_scaling.py`. Run correctness tests and rendering outside the
measurement window. Retain the first attempt and any failure. Pool reuse is not
tree reuse, and faster computation does not establish stronger play. The first
54 conditions are retained in `docs/parallel-scaling-results.json`. Check the
accounting and both generated reports with
`python tools/render_parallel_scaling.py --check`. Drop `--check` only to render
the saved measurements. Neither operation runs the experiment. Keep the measured
source revision separate from the later site build revision.

The [same forest execution control](docs/same-forest-protocol.json) is a separate
protocol. Keep its implementation and protocol committed before collecting any
results with `tools/run_same_forest.py`. Tiny correctness fixtures may run first.
Sequential and process paths must agree on every computational receipt field,
including failures and unused work. Do not reuse or replace the earlier study's
result files. Research for this follow up came after that completed evaluation.
The retained first attempt is `docs/same-forest-results.json`, measured at
`3adf64e618c277721d7ea36629cc934d0145a3ac`. Check all receipts and regenerate its
Markdown and HTML presentations with `python tools/render_same_forest.py`.
Add `--check` to validate without writing. Neither operation executes search.
The site builder also checks this report before copying it. Preserve the exact
first attempt bytes and keep evaluated source distinct from report source.

The [serial profiling protocol](docs/serial-profile.md) is a separate diagnostic
for a possible narrow optimization. Commit its tested runner and protocol before
measurement. Preserve the control and instrumented receipts, including any
shortfall or mismatch. Profile time includes instrumentation overhead and does
not establish an optimization speedup. A proposed change needs a separate
committed comparison protocol before its timing evidence is collected.

## Development container and public site

Open this repository in Codespaces or use VS Code Dev Containers. The container uses Python 3.11 and installs the project into `.venv` during setup. Its image is pinned by digest. The `Project access` workflow builds that same environment and runs `.devcontainer/smoke.sh`. Runtime dependencies still follow the project configuration. Codespaces uses the creating account's compute and storage allowance.

Run `python tools/build_site.py` to assemble the public page in `_site`, then `python -m http.server 8080 --directory _site` to preview it. The builder copies only the listed example files. The page reads saved evidence; it does not silently rerun the experiment or claim current results. Pages deploys from `main` after the site and development environment checks pass.

The page uses the Clair/Obscur roles pinned in `presentation/tokens.json`.
`tools/presentation.py` generates the small CSS adapter. Keep action values,
visit counts, units and selection history independent of appearance. The
historical SVG retains its original colors and bytes. The build records hashes,
the rendering revision and the saved decision's original source revision in
`_site/presentation.json`. A dirty local build is labeled as such.

The [decision figure](docs/visual-example.md#rebuild-the-figure-without-another-search)
has a separate maintained renderer and optional authoring dependencies. Supply
explicit Inter files to rebuild its two editions from retained values. Ordinary
site builds verify the committed figures without rerunning a search or fetching
fonts. Preserve the original diagram, decision source and later study results.

Use these extra checks for presentation changes:

```sh
node --test tests/selection-state.test.mjs
npm ci --ignore-scripts
python tools/render_parallel_scaling.py --check
python tools/build_site.py
npm run test:browser
```

Playwright is a development dependency only. Set `MCTS_BROWSER_CHANNEL=chrome`
to use an installed Chrome in isolated headless processes. CI uses its installed
Chrome with the sandbox enabled. Otherwise install Playwright's matching browser
with `npx playwright install chromium`. Tests never attach to an existing browser
or profile. `MCTS_SCREENSHOT_DIR` optionally saves isolated page captures outside
the checkout.

The browser suite checks both appearances, Auto, failed storage, no JavaScript,
selection/history, keyboard navigation, narrow screens, enlarged text, print and
forced colors. Set `MCTS_REQUIRE_INTER=1` only in an environment with the six
documented local Inter faces installed. That strict check requires actual glyph
providers for 400, 600, 700 and genuine italics, separately from the missing-font
fallback control. These headless page checks do not establish native client or
physical display acceptance. No font files are bundled or fetched by the page.
