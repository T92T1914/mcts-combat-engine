# Read the visual example

<a href="visual-example-data.json">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="mcts-decision-obscur.png">
    <source media="(prefers-color-scheme: light)" srcset="mcts-decision-clair.png">
    <img src="mcts-decision-clair.png" alt="One recorded decision after 10,000 simulations. Spark has mean shaped reward 0.532, Pass 0.506 and Weakness Mark 0.495. Exact visits are 5,724, 2,445 and 1,831 respectively. Reward is not a win probability." width="480">
  </picture>
</a>

The search ranks three actions after 10,000 simulations. Its shaped reward describes this decision and is not a win probability. The example and its reproduction command are below.

## Reproduce the values

Run from this repository using its documented Python environment.
Evidence was checked against commit `a82e1a6`.

```sh
python demo.py boss --sims 10000 --seed 7 --horizon 6
```

The public synthetic boss scenario starts from the demo's fixed deal seed 7.
The search also uses seed 7 and a horizon of six. The safety time cap was not
reached. Reward values in the image use the three decimal places printed by
the demo; visit counts are exact. The reward axis begins at zero and is not
a probability axis. No confidence interval is inferred from those visits.

The boss retaliates when a trap is cast. Weakness Mark is therefore ranked
below passing in this particular state. This is not a universal move ranking.
The separate [paired benchmark](benchmark-results.md) shows the full scenario
comparison, including the boss result that decreased by one game after a
correctness repair.

## Inspect the source

The [underlying values](visual-example-data.json) include the source and
conditions. The [Clair SVG](mcts-decision-clair.svg) and
[Obscur SVG](mcts-decision-obscur.svg) carry outlined Inter labels. The
[original PNG](mcts-decision-example.png) and [original SVG](mcts-decision-example.svg)
retain their recorded bytes.
The figure is a visual explanation of the public implementation, not a
screenshot of an external application.

## Rebuild the figure without another search

The maintained renderer reads the saved decision. It does not execute the demo,
benchmark or parallel scaling study. Supply the six official static Inter TTFs
from one release in a local directory:

```sh
python -m pip install -r requirements-figures.txt
python tools/render_decision_figure.py --font-dir /path/to/Inter/extras/ttf
python tools/render_decision_figure.py --check
```

Each font's name, weight, italic flag and Latin glyph coverage are checked.
Regular, Semibold, Bold and genuine Italic supply this figure's labels. The
[rendering receipt](mcts-decision-figure.json) records all six input font hashes,
retained values, token and renderer identities, and output hashes. PNGs rasterize
the intended Inter glyphs. SVGs outline those same labels, with selectable
explanations and JSON available here. No font files are distributed or downloaded.

Both editions keep the same zero based reward scale and action identities.
Spark stays amber, Pass blue and Weakness Mark neutral. Visits remain separate
counts, not uncertainty estimates. The site follows its effective Auto, Clair or
Obscur choice. GitHub uses light/dark picture sources and a Clair fallback.
Print uses Clair. The compact layout keeps the figure readable in a narrow README.
Site builds verify the committed outputs without fonts or a silent rebuild.

Source `a82e1a6` belongs to this old decision, not the later
[parallel scaling study](parallel-scaling-results.md). The retained values and
original images are unchanged.
