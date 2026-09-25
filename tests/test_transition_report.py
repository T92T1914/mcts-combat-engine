"""Synthetic accounting records test the report before new game outcomes exist."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.render_transition_comparison import (
    BASES,
    LABELS,
    SCENARIOS,
    assemble_report,
    protocol_hash,
    render,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "docs/transition-comparison-protocol.json"
PROTOCOL = json.loads(PROTOCOL_PATH.read_text("utf-8"))
PROTOCOL_HASH = protocol_hash(PROTOCOL_PATH)


def fixture():
    """Invented one-round wins are bookkeeping fixtures, not simulator outcomes."""
    runs = []
    for seed in BASES:
        row = {}
        for label in LABELS:
            row[label] = {
                "games": 5,
                "wins": 5,
                "win_rate": 1.0,
                "avg_score": 1.0,
                "avg_rounds_to_win": 1.0,
                "game_results": [
                    {
                        "environment_seed": 200 + i,
                        "policy_seed": seed + i,
                        "score": 1.0,
                        "clean_win": True,
                        "rounds": 1,
                        "terminal_result": 1.0,
                    }
                    for i in range(5)
                ],
            }
        one = row[LABELS[2]]
        one["one_round_work"] = {
            "decision_transitions": [294] * 5,
            "samples_per_action": None,
            "horizon_rounds": 1,
        }
        one["transition_work"] = {
            "decision_records": [
                {
                    "max_transitions": 300,
                    "transitions": 294,
                    "unused_transitions": 6,
                    "actions": 7,
                    "intended_sweeps": 42,
                    "completed_sweeps": 42,
                    "stop_reasons": ["transition_allowance"],
                }
                for _ in range(5)
            ],
            "incomplete_decisions": [],
        }
        search = row[LABELS[3]]
        search["search_work"] = {
            "decision_simulations": [60] * 5,
            "below_requested_simulations": None,
        }
        search["transition_work"] = {
            "decision_records": [
                {
                    "max_transitions": 300,
                    "transitions": 297,
                    "unused_transitions": 3,
                    "simulations": 60,
                    "stop_reasons": ["transition_allowance"],
                }
                for _ in range(5)
            ],
            "incomplete_decisions": [],
        }
        runs.append(
            {
                "schema_version": 3,
                "environment": {"python": "synthetic", "platform": "synthetic"},
                "elapsed_s": 1.0,
                "settings": {
                    "games_per_policy": 5,
                    "game_seeds": list(range(200, 205)),
                    "policy_seeds": list(range(seed, seed + 5)),
                    "search_seed": seed,
                    "mode": "transition_allowance",
                    "max_simulations": 300,
                    "max_transitions": 300,
                    "time_limit_ms": 60000,
                    "horizon": 5,
                    "processes": 1,
                    "one_round_samples_per_action": None,
                    "one_round_time_limit_ms": 60000,
                    "search_seed_scope": (
                        "reset_per_scenario_then_persistent_across_games"
                    ),
                    "policy_seed_format": (
                        "policy-v1:{seed} (Python Random string seed)"
                    ),
                },
                "results": {name: copy.deepcopy(row) for name in SCENARIOS},
            }
        )
    return assemble_report(
        runs,
        protocol_sha256=PROTOCOL_HASH,
        source_revision="a" * 40,
        source_hashes={p: "b" * 64 for p in PROTOCOL["interface"]["source_paths"]},
        evaluation={"benchmark_elapsed_seconds": 3.0},
    )


class TestTransitionReport(unittest.TestCase):
    def test_cli_preserves_inputs_and_checks_rendered_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "synthetic.json"
            output = Path(temporary) / "synthetic.md"
            data.write_text(json.dumps(fixture()), encoding="utf-8")
            original_data = data.read_bytes()
            original_protocol = PROTOCOL_PATH.read_bytes()
            command = [
                sys.executable, str(ROOT / "tools/render_transition_comparison.py"),
                "--data", str(data), "--output",
            ]
            for destination in (data, PROTOCOL_PATH):
                result = subprocess.run(
                    command + [str(destination)], capture_output=True,
                    text=True, timeout=15, cwd=ROOT,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("output must differ", result.stderr)
            self.assertEqual(data.read_bytes(), original_data)
            self.assertEqual(PROTOCOL_PATH.read_bytes(), original_protocol)
            for extra in ([], ["--check"]):
                result = subprocess.run(
                    command + [str(output)] + extra,
                    capture_output=True, text=True, timeout=15, cwd=ROOT,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            output.write_text("altered report", encoding="utf-8")
            result = subprocess.run(
                command + [str(output), "--check"],
                capture_output=True, text=True, timeout=15, cwd=ROOT,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("differs from retained data", result.stderr)

    def test_synthetic_complete_record_and_render(self):
        report = fixture()
        validate(report, PROTOCOL, PROTOCOL_HASH)
        text = render(report)
        self.assertIn("Recorded time shortfalls: 0", text)
        self.assertIn("five environments per scenario, not 15", text)
        self.assertIn("Mean shaped score", text)
        self.assertIn("All recorded games", text)
        self.assertNotIn("z =", text)
        self.assertNotIn("95%", text)
        for scenario in SCENARIOS:
            for seed in BASES:
                self.assertIn(f"| {scenario} | {seed} | 5/5 | 5/5 | 5/5 | 5/5 |", text)

    def test_time_shortfall_is_valid_evidence_and_visible(self):
        report = fixture()
        result = report["runs"][0]["results"]["duel"][LABELS[2]]
        record = result["transition_work"]["decision_records"][0]
        record.update(
            transitions=7,
            unused_transitions=293,
            completed_sweeps=1,
            stop_reasons=["time_limit"],
        )
        result["transition_work"]["incomplete_decisions"] = [0]
        result["one_round_work"]["decision_transitions"][0] = 7
        validate(report, PROTOCOL, PROTOCOL_HASH)
        self.assertIn("Recorded time shortfalls: 1", render(report))

    def test_loss_and_unfinished_game_remain_distinct(self):
        report = fixture()
        result = report["runs"][0]["results"]["boss"]["random"]
        result["game_results"][0].update(score=0, clean_win=False, terminal_result=0)
        result["game_results"][1].update(
            score=0.25, clean_win=False, terminal_result=None, rounds=30
        )
        result.update(wins=3, win_rate=0.6, avg_score=0.65)
        validate(report, PROTOCOL, PROTOCOL_HASH)
        text = render(report)
        self.assertIn("| boss | 7 | random | 201 | unfinished | 30 |", text)
        self.assertIn("| boss | 7 | 3/5 |", text)

    def test_assembler_preserves_raw_records_and_maps_games(self):
        report = fixture()
        runs = copy.deepcopy(report["runs"])
        for run in runs:
            for row in run["results"].values():
                for label in LABELS[2:]:
                    del row[label]["transition_work"]["game_decision_ranges"]
        original = copy.deepcopy(runs)
        result = assemble_report(
            runs,
            protocol_sha256=PROTOCOL_HASH,
            source_revision="a" * 40,
            source_hashes={},
            evaluation={},
        )
        self.assertEqual(runs, original)
        spans = result["runs"][0]["results"]["duel"][LABELS[3]]["transition_work"][
            "game_decision_ranges"
        ]
        self.assertEqual(
            spans[1],
            {
                "environment_seed": 201,
                "policy_seed": 8,
                "start_index": 1,
                "stop_index": 2,
            },
        )

    def test_invalid_records_fail_with_value_error(self):
        mutations = {
            "missing repeat": lambda r: r["runs"].pop(),
            "wrong hash": lambda r: r.update(protocol_sha256="wrong"),
            "missing revision": lambda r: r.update(source_revision="working tree"),
            "missing source": lambda r: r["source_hashes"].pop("engine/mcts.py"),
            "different environment": lambda r: r["runs"][0]["settings"].update(
                game_seeds=list(range(5))
            ),
            "different budget": lambda r: r["runs"][0]["settings"].update(
                max_transitions=301
            ),
            "wrong elapsed": lambda r: r["evaluation"].update(
                benchmark_elapsed_seconds=2
            ),
            "missing scenario": lambda r: r["runs"][0]["results"].pop("boss"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                report = fixture()
                mutate(report)
                with self.assertRaises(ValueError):
                    validate(report, PROTOCOL, PROTOCOL_HASH)
        for root in (None, [], "wrong"):
            with self.subTest(root=root), self.assertRaises(ValueError):
                validate(root, PROTOCOL, PROTOCOL_HASH)

    def test_work_contradictions_are_rejected(self):
        mutations = {
            "binding simulation cap": lambda r: r["decision_records"][0].update(
                transitions=300,
                unused_transitions=0,
                simulations=300,
                stop_reasons=["transition_allowance", "simulation_cap"],
            ),
            "overspend": lambda r: r["decision_records"][0].update(transitions=301),
            "boolean count": lambda r: r["decision_records"][0].update(
                transitions=True
            ),
            "negative unused": lambda r: r["decision_records"][0].update(
                unused_transitions=-1
            ),
            "bad remainder": lambda r: r["decision_records"][0].update(
                unused_transitions=2
            ),
            "false time stop": lambda r: r["decision_records"][0].update(
                stop_reasons=["transition_allowance", "time_limit"]
            ),
            "missing decision": lambda r: r["decision_records"].pop(),
            "wrong game mapping": lambda r: r["game_decision_ranges"][0].update(
                stop_index=2
            ),
            "false shortfall": lambda r: r.update(incomplete_decisions=[0]),
            "missing reasons": lambda r: r["decision_records"][0].update(
                stop_reasons=[]
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                report = fixture()
                work = report["runs"][0]["results"]["duel"][LABELS[3]][
                    "transition_work"
                ]
                mutate(work)
                with self.assertRaises(ValueError):
                    validate(report, PROTOCOL, PROTOCOL_HASH)

    def test_partial_sweep_and_hidden_shortfall_are_rejected(self):
        for mutation in ("sweep", "hidden"):
            with self.subTest(mutation=mutation):
                report = fixture()
                work = report["runs"][0]["results"]["duel"][LABELS[2]][
                    "transition_work"
                ]
                record = work["decision_records"][0]
                if mutation == "sweep":
                    record.update(transitions=293, unused_transitions=7)
                else:
                    record.update(
                        transitions=7,
                        unused_transitions=293,
                        completed_sweeps=1,
                        stop_reasons=["time_limit"],
                    )
                with self.assertRaises(ValueError):
                    validate(report, PROTOCOL, PROTOCOL_HASH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
