"""The retained study preserves every condition and reconciles to its game records."""
import hashlib
import json
import unittest
from pathlib import Path

from tools.render_comparison import render

ROOT = Path(__file__).resolve().parents[1]


class TestComparisonRecord(unittest.TestCase):
    def test_all_frozen_conditions_and_outcomes_are_retained(self):
        protocol_bytes = (ROOT / "docs/comparison-protocol.json").read_text(
            "utf-8-sig").encode("utf-8")
        protocol = json.loads(protocol_bytes)
        report = json.loads((ROOT / "docs/comparison-results.json").read_text("utf-8"))
        self.assertEqual(hashlib.sha256(protocol_bytes).hexdigest(),
                         report["protocol_sha256"])
        self.assertEqual(len(report["runs"]), len(protocol["replicates"]))
        for run, repeat in zip(report["runs"], protocol["replicates"], strict=True):
            settings = run["settings"]
            seeds = protocol["environment_seeds"]
            self.assertEqual(settings["game_seeds"], seeds)
            self.assertEqual(settings["search_seed"], repeat["search_seed"])
            self.assertEqual(settings["policy_seeds"],
                             list(range(repeat["policy_seed"],
                                        repeat["policy_seed"] + len(seeds))))
            self.assertEqual(settings["max_simulations"],
                             protocol["mcts"]["simulations_per_decision"])
            self.assertEqual(settings["one_round_samples_per_action"],
                             protocol["one_round"]["samples_per_action"])
            self.assertEqual(settings["horizon"], protocol["mcts"]["horizon_rounds"])
            self.assertEqual(settings["time_limit_ms"],
                             protocol["mcts"]["safety_time_limit_ms"])
            self.assertEqual(settings["processes"], 1)
            self.assertEqual(list(run["results"]), protocol["scenarios"])
            for row in run["results"].values():
                self.assertEqual(len(row), len(protocol["policies"]))
                for result in row.values():
                    games = result["game_results"]
                    self.assertEqual([g["environment_seed"] for g in games], seeds)
                    self.assertEqual([g["policy_seed"] for g in games],
                                     settings["policy_seeds"])
                    self.assertEqual(len(games), result["games"])
                    wins = [g for g in games if g["terminal_result"] == 1.0]
                    self.assertEqual(len(wins), result["wins"])
                    self.assertEqual(result["win_rate"], len(wins) / len(games))
                    self.assertAlmostEqual(result["avg_score"],
                                           sum(g["score"] for g in games) / len(games))
                    rounds = (sum(g["rounds"] for g in wins) / len(wins)
                              if wins else None)
                    self.assertEqual(rounds, result["avg_rounds_to_win"])
                    for game in games:
                        self.assertEqual(game["clean_win"], game in wins)
                        if game["terminal_result"] is not None:
                            self.assertEqual(game["score"], game["terminal_result"])
                        else:
                            self.assertEqual(game["rounds"], 30)
                search = row["mcts (300 sims)"]["search_work"]
                self.assertEqual(set(search["decision_simulations"]), {300})
                self.assertEqual(search["below_requested_simulations"], 0)
                one = row["one_round (8 samples/action)"]["one_round_work"]
                self.assertTrue(all(n >= 8 and n % 8 == 0
                                    for n in one["decision_transitions"]))
                for label, key, field in (
                    ("mcts (300 sims)", "search_work", "decision_simulations"),
                    ("one_round (8 samples/action)", "one_round_work",
                     "decision_transitions"),
                ):
                    rounds = sum(g["rounds"] for g in row[label]["game_results"])
                    self.assertEqual(len(row[label][key][field]), rounds)

    def test_report_rebuild_preserves_all_tables(self):
        report = json.loads((ROOT / "docs/comparison-results.json").read_text("utf-8"))
        self.assertEqual((ROOT / "docs/comparison-results.md").read_text("utf-8"),
                         render(report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
