"""Check the retained study without sampling or revising its outcomes."""
import json
import unittest
from pathlib import Path

from tools.render_transition_comparison import protocol_hash, render, validate

ROOT = Path(__file__).resolve().parents[1]


class TestRetainedTransitionStudy(unittest.TestCase):
    def test_all_declared_games_and_work_reconcile(self):
        protocol_path = ROOT / "docs/transition-comparison-protocol.json"
        protocol = json.loads(protocol_path.read_text("utf-8"))
        report = json.loads(
            (ROOT / "docs/transition-comparison-results.json").read_text("utf-8")
        )
        validate(report, protocol, protocol_hash(protocol_path))
        self.assertEqual(
            report["source_revision"], "c25ad84a2d07259ec7c94ce99c4a6e623be18413"
        )
        games = [game for run in report["runs"]
                 for row in run["results"].values() for result in row.values()
                 for game in result["game_results"]]
        self.assertEqual(len(games), 180)
        self.assertTrue(any(game["terminal_result"] == 0 for game in games))
        self.assertTrue(any(game["terminal_result"] is None for game in games))

    def test_saved_report_matches_retained_records(self):
        report = json.loads(
            (ROOT / "docs/transition-comparison-results.json").read_text("utf-8")
        )
        self.assertEqual(
            (ROOT / "docs/transition-comparison-results.md").read_text("utf-8"),
            render(report),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
