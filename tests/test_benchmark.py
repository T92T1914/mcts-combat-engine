"""Benchmark tests: the results table is rendered from data, never typed in."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import benchmark


def _result(wins, games=60, rounds=20.0):
    return {"games": games, "wins": wins, "win_rate": wins / games,
            "avg_score": wins / games, "avg_rounds_to_win": rounds}


class TestRenderMarkdown(unittest.TestCase):
    def setUp(self):
        self.results = {
            "boss": {"random": _result(12, rounds=25.9),
                     "greedy": _result(2, rounds=17.0),
                     "mcts (120 ms)": _result(33, rounds=23.4)},
            # a row the search loses, to prove bold and z follow the data
            "upset": {"random": _result(40),
                      "greedy": _result(10),
                      "mcts (120 ms)": _result(30, rounds=None)},
        }
        self.text = benchmark.render_markdown(
            self.results, games=60, budget_ms=120,
            machine="test box", elapsed_s=90.0)

    def test_provenance_header(self):
        self.assertIn("60 games per policy per scenario", self.text)
        self.assertIn("120 ms of search per decision, single process", self.text)
        self.assertIn(f"Python {sys.version.split()[0]}", self.text)
        self.assertIn("test box", self.text)
        self.assertIn("in 1.5 min", self.text)

    def test_row_carries_intervals_bold_and_z(self):
        # 33/60 -> 42.5-66.9%, 12/60 -> 11.8-31.8%, z = 3.96: the first
        # benchmark run's boss row (2026-09-04) as a rendering fixture; the
        # README's committed table is a later run with its own numbers
        self.assertIn(
            "| boss | 20% (12–32) · 25.9r | 3% (1–11) · 17.0r "
            "| **55% (42–67) · 23.4r** | z = 3.96 vs random |",
            self.text)

    def test_bold_goes_to_the_winner_not_the_search(self):
        self.assertIn(
            "| upset | **67% (54–77) · 20.0r** | 17% (9–28) · 20.0r "
            "| 50% (38–62) | z = -1.85 vs random |",
            self.text)

    def test_console_cell_is_plain_ascii(self):
        self.assertEqual(benchmark._cell(_result(33, rounds=23.4)),
                         "55% (42-67) / 23.4r")


class TestCommandLine(unittest.TestCase):
    def test_fixed_budget_runs_are_repeatable_and_label_the_budget(self):
        def run_once():
            policies = benchmark._policies(1, sims=20, seed=42)
            return {name: benchmark.play_match(
                benchmark.SCENARIOS['boss'], policy, games=2)
                for name, policy in policies.items()}

        result = run_once()
        self.assertEqual(result, run_once())
        text = benchmark.render_markdown({'boss': result}, 2, 1,
                                          sims=20, seed=42)
        self.assertIn('20 simulations per decision, search seed 42', text)
        self.assertIn('mcts (20 sims)', text)

    def test_tiny_run_prints_table_and_writes_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results.md"
            argv = ["benchmark.py", "1", "10", "--markdown", str(out),
                    "--machine", "ci"]
            buf = io.StringIO()
            with (mock.patch.object(sys, "argv", argv),
                  contextlib.redirect_stdout(buf)):
                benchmark.main()
            console = buf.getvalue()
            for scenario in ("duel", "gauntlet", "boss"):
                self.assertIn(scenario, console)
            self.assertIn("z =", console)
            text = out.read_text(encoding="utf-8")
            self.assertIn("| scenario | random | greedy | mcts (10 ms) |", text)
            self.assertIn("1 games per policy", text)
            self.assertIn("; ci.", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
