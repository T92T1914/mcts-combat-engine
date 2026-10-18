"""Reproduce the frozen, serial equal-transition horizon configuration study.

This active study uses modeled roots and an external two-round action-pricing
target. It does not replay episodes or alter saved-decision eligibility.
"""

# The standalone companion entry needs its own root before local imports.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.mcts as search_module
from engine import MCTS, Card, CardType, Combatant, Element, GameState
from game import episode_record as records
from reference import adaptive_report, consumer, report

DATA = ROOT / "docs" / "two-round-horizon"
PINS = {
    "protocol.json": "342353130d98af33cde4c3df46b9e4f5742706ea4644099751123a7f7f4d51fc",
    "inputs.json": "6471f5fb5414c2efaeddccb3cd40f443804a8cc93a509ed113e6b0b40dedbd5a",
    "seeds.json": "b77dad218f5c1241b0e2b83844ce46f6fc4486c5cf877a2feabc6e7511d59a0f",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def fraction(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def ratio(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def action_key(value):
    return value["card_idx"], value["target_idx"]


def action_data(action):
    return {"card_idx": action.card_idx, "target_idx": action.target_idx}


def construct_state(value):
    """Construct only the already admitted, effect-free public model subset."""
    records._state(value, "study state")
    adaptive_report.qualified_state(value)

    def card(source):
        fields = dict(source)
        fields["element"] = Element(fields["element"])
        fields["card_type"] = CardType(fields["card_type"])
        return Card(**fields)

    def fighter(source):
        fields = dict(source)
        fields["element"] = Element(fields["element"])
        for name in ("resist", "boost"):
            fields[name] = {Element(key): item for key, item in fields[name].items()}
        if fields["base_attack"] is not None:
            fields["base_attack"] = card(fields["base_attack"])
        return Combatant(**fields)

    state = GameState(
        player=fighter(value["player"]),
        enemies=[fighter(item) for item in value["enemies"]],
        hand=[card(item) for item in value["hand"]],
        round_num=value["round_num"],
        boss_rules=[],
    )
    require(
        records.canonical(records.normalized(state)) == records.canonical(value),
        "public model reconstruction changed the normalized root",
    )
    return state


def price_actions(reference, state):
    adaptive_report.validate_reference_report(reference)
    require(reference["status"] == "complete", "reference did not complete")
    require(
        records.canonical(reference["selected_state"]) == records.canonical(state),
        "reference root differs from the study input",
    )
    rows = reference["evaluation"]["actions"]
    require(
        all(
            observation["terminal"] is None
            for row in rows
            for observation in row["observations"]
        ),
        "a complete first-round branch is terminal; equal-work gate refused",
    )
    values = {action_key(row["action"]): fraction(row["value"]) for row in rows}
    require(
        len(values) == len(rows) and len(values) >= 2,
        "physical root actions are duplicate or insufficient",
    )
    return values


def collect_one(state, seed, horizon, values):
    require(type(seed) is int and 0 <= seed < 2**64, "invalid frozen seed")
    require(horizon in (1, 2), "only the two declared horizons are admitted")
    before = records.canonical(records.normalized(state))
    calls = 0
    original = search_module.advance_round

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    search = MCTS(
        horizon_rounds=horizon,
        max_sims=64 // horizon,
        max_transitions=64,
        exploration=1.2,
        rng=random.Random(seed),
    )
    with patch.object(search_module, "advance_round", counted):
        ranked = search.search(state, time_budget_ms=None)
    require(bool(ranked), "search returned no recommendation")
    selected = action_data(ranked[0].action)
    require(action_key(selected) in values, "unknown selected physical action")
    require(
        (
            search.last_sims,
            search.last_transitions,
            calls,
            search.last_unused_transitions,
        )
        == (64 // horizon, 64, 64, 0),
        "requested and independently counted completed work differ",
    )
    require(
        set(search.last_stop_reasons) == {"simulation_cap", "transition_allowance"},
        "unexpected stopping reason",
    )
    require(
        records.canonical(records.normalized(state)) == before,
        "search mutated the original root",
    )
    statistics = [
        {
            "action": action_data(action),
            "visits": visits,
            "value_sum_hex": value_sum.hex(),
        }
        for action, visits, value_sum in search.last_root_statistics
    ]
    require(
        sum(item["visits"] for item in statistics) == 64 // horizon,
        "root visit total differs from completed simulations",
    )
    return {
        "horizon": horizon,
        "seed": seed,
        "selected_action": selected,
        "loss": ratio(max(values.values()) - values[action_key(selected)]),
        "simulations": search.last_sims,
        "transitions": search.last_transitions,
        "counted_advance_round_calls": calls,
        "unused_transitions": 0,
        "stop_reasons": list(search.last_stop_reasons),
        "statistics": statistics,
    }


def logarithm_upper():
    """ln(80)=6 ln(2)+ln(5/4), bounded by the positive atanh series."""

    def series(x):
        count = 40
        partial = 2 * sum(
            (x ** (2 * k + 1) / (2 * k + 1) for k in range(count)), Fraction(0)
        )
        tail = 2 * x ** (2 * count + 1) / ((2 * count + 1) * (1 - x * x))
        return partial + tail

    return 6 * series(Fraction(1, 3)) + series(Fraction(1, 9))


def sqrt_upper(value):
    require(value >= 0, "negative square-root argument")
    scale = 10**18
    result = Fraction(
        math.isqrt(value.numerator * scale**2 // value.denominator) + 1, scale
    )
    require(result * result >= value, "square-root enclosure failed")
    return result


def summarize(cells, cases, blocks, values):
    by_key = {(cell["block"], cell["case"], cell["horizon"]): cell for cell in cells}
    require(
        len(by_key) == len(cells) == blocks * len(cases) * 2,
        "phase has duplicate or missing cells",
    )
    differences = []
    state_rows = []
    for case in cases:
        losses = {
            h: [fraction(by_key[b, case, h]["loss"]) for b in range(blocks)]
            for h in (1, 2)
        }
        state_rows.append(
            {
                "case": case,
                "mean_loss_h1": ratio(sum(losses[1]) / blocks),
                "mean_loss_h2": ratio(sum(losses[2]) / blocks),
                "optimal_hits_h1": losses[1].count(0),
                "optimal_hits_h2": losses[2].count(0),
                "root_values": [
                    {
                        "action": {"card_idx": key[0], "target_idx": key[1]},
                        "value": ratio(value),
                    }
                    for key, value in values[case].items()
                ],
            }
        )
    for block in range(blocks):
        difference = sum(
            (
                fraction(by_key[block, case, 1]["loss"])
                - fraction(by_key[block, case, 2]["loss"])
                for case in cases
            ),
            Fraction(0),
        ) / len(cases)
        require(-1 <= difference <= 1, "block contrast outside declared range")
        differences.append(difference)
    average = sum(differences) / blocks
    variance = sum(((value - average) ** 2 for value in differences), Fraction(0)) / (
        blocks - 1
    )
    log = logarithm_upper()
    radius = sqrt_upper(2 * variance * log / blocks) + 14 * log / (3 * (blocks - 1))
    lower, upper = (
        max(Fraction(-1), average - radius),
        min(Fraction(1), average + radius),
    )
    direction = (
        "horizon_two" if lower > 0 else "horizon_one" if upper < 0 else "inconclusive"
    )
    return {
        "states": state_rows,
        "blocks": blocks,
        "block_differences": list(map(ratio, differences)),
        "mean_difference": ratio(average),
        "sample_variance": ratio(variance),
        "interval": {
            "lower": ratio(lower),
            "upper": ratio(upper),
            "radius_upper": ratio(radius),
            "log80_upper": ratio(log),
        },
        "direction_under_declared_assumptions": direction,
        "positive_zero_negative_blocks": [
            sum(value > 0 for value in differences),
            differences.count(0),
            sum(value < 0 for value in differences),
        ],
    }


def run(phase, output):
    captured = {}
    for name, pin in PINS.items():
        body = (DATA / name).read_bytes()
        require(
            len(body) <= 1_048_576 and digest(body) == pin,
            "frozen input bytes differ: " + name,
        )
        captured[name] = body
    protocol, inputs, seeds = (json.loads(captured[name]) for name in PINS)
    spec = protocol["phases"][phase]
    identity = consumer.reference_identity()
    require(
        report.qualified_engine_files(
            identity["decision_consumer"]["engine_files_sha256"]
        ),
        "unqualified engine source map",
    )
    output.mkdir(exist_ok=False)
    receipt = {
        "phase": phase,
        "status": "running",
        "implementation": identity,
        "collector_sha256": digest(Path(__file__).read_bytes()),
        "frozen_inputs_sha256": dict(PINS),
        "completed_cells": 0,
    }
    cells, values, reference_ids = [], {}, {}
    try:
        for case in spec["cases"]:
            state = inputs["cases"][case]
            path = output / (case + ".state.json")
            path.write_bytes(encoded(state))
            reference = consumer.reference_decision(
                path,
                model=adaptive_report.MODEL,
                method=adaptive_report.METHOD,
                state_input=True,
                **{
                    key: value
                    for key, value in protocol["reference"].items()
                    if key.startswith("max_")
                },
            )
            body = encoded(reference)
            (output / (case + ".reference.json")).write_bytes(body)
            values[case] = price_actions(reference, state)
            require(
                reference["implementation"] == identity, "reference identity drifted"
            )
            reference_ids[case] = {"bytes": len(body), "sha256": digest(body)}
        with (output / "cells.jsonl").open("xb") as stream:
            for block, labels in enumerate(seeds[phase]):
                for case in spec["cases"]:
                    state = construct_state(inputs["cases"][case])
                    for horizon in (1, 2):
                        cell = collect_one(
                            state, labels[case][str(horizon)], horizon, values[case]
                        )
                        cell.update(case=case, block=block)
                        cells.append(cell)
                        stream.write(
                            (
                                json.dumps(cell, sort_keys=True, allow_nan=False) + "\n"
                            ).encode()
                        )
                        receipt["completed_cells"] = len(cells)
        require(consumer.reference_identity() == identity, "source identity changed")
        require(
            all((DATA / name).read_bytes() == body for name, body in captured.items()),
            "original frozen input changed",
        )
        result = {
            "phase": phase,
            "status": "complete",
            "implementation": identity,
            "frozen_inputs_sha256": dict(PINS),
            "reference_reports": reference_ids,
            "summary": summarize(cells, spec["cases"], spec["blocks"], values),
            "cells": cells,
        }
        (output / "results.json").write_bytes(encoded(result))
        receipt.update(
            status="complete",
            results_sha256=digest(encoded(result)),
            search_transitions=sum(cell["transitions"] for cell in cells),
        )
    except BaseException as error:
        receipt.update(
            status="incomplete", error=type(error).__name__ + ": " + str(error)
        )
        raise
    finally:
        (output / "receipt.json").write_bytes(encoded(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("exploratory", "deciding"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.phase, args.output)))


if __name__ == "__main__":
    main()
