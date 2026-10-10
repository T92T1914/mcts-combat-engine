"""Saved reference admission preserves exact physical choices and passive reads."""

from __future__ import annotations

import copy
import hashlib
import json
import random
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from test_episode_decision import guarded_routes
from test_episode_inspection import Artifact, synthetic_decision_report

from engine import GameState
from game import episode_decision
from game.episode_record import EpisodeInputError, canonical
from reference import report


def literal_decision(*, version=2, no_work=False):
    """Synthetic representation, never recorded, searched or numerically evaluated."""
    value = synthetic_decision_report(zero=True)
    state = value["selected_state"]
    state["boss_rules"] = []
    enemy = copy.deepcopy(state["enemies"][1])
    enemy.update(is_boss=False, base_attack=None, pips=0, power_pips=0, dots=[])
    state["enemies"] = [enemy]
    state["player"]["dots"] = []
    card = copy.deepcopy(state["hand"][0])
    card.update(
        name="Duplicate utility",
        card_type="utility",
        pip_cost=0,
        damage_min=0,
        damage_max=0,
        heal=0,
        dot_tick=0,
        dot_rounds=0,
        modifier=0,
        accuracy=1,
        hits_all=False,
    )
    state["hand"] = [copy.deepcopy(card), copy.deepcopy(card)]
    value["value_semantics"] = report.SEARCH_VALUE_SEMANTICS
    value["schema_version"] = version
    value["implementation"]["engine_files_sha256"] = copy.deepcopy(
        report.REFERENCE_ENGINE_FILES_SHA256
    )
    rows = []
    for index, identity in enumerate(
        (
            {"card_idx": None, "target_idx": None},
            {"card_idx": 0, "target_idx": None},
            {"card_idx": 1, "target_idx": None},
        )
    ):
        visits, total = ((4, 3.0), (12, 6.0), (0, 0))[index]
        if no_work:
            visits, total = 0, 0
        rows.append(
            {
                **identity,
                "label": "Pass" if index == 0 else card["name"],
                "status": "sampled" if visits else "unvisited",
                "visits": visits,
                "value_sum": total,
                "mean_shaped_reward": total / visits if visits else None,
            }
        )
    value["legal_actions"] = rows
    identities = [
        {name: row[name] for name in ("card_idx", "target_idx")} for row in rows
    ]
    value["ranking"] = [] if no_work else identities[:2]
    value["recommendation"] = None if no_work else {**identities[0], "label": "Pass"}
    value["configuration"].update(
        horizon_rounds=1,
        max_sims=0 if no_work else 16,
        max_transitions=0 if no_work else 16,
    )
    value.update(
        status="no_work" if no_work else "decision",
        search_performed=not no_work,
        elapsed_seconds=0 if no_work else 0.2,
    )
    value["work"] = {
        "simulations": 0 if no_work else 16,
        "transitions": 0 if no_work else 16,
        "unused_transitions": 0,
        "stop_reasons": (
            ["zero_requested_simulations"] if no_work else ["simulation_cap"]
        ),
    }
    if version == 2:
        value.update(
            root_encounter_order=[] if no_work else identities[1::-1], derivation=None
        )
        value["configuration"].update(
            final_action_rule="mean_visits", tie_break="root_encounter_order"
        )
    recorded = value["stored_provenance"]["implementation"]
    current = value["implementation"]
    runtime_current = {name: current[name] for name in report.RUNTIME_FIELDS}
    runtime_recorded = {name: recorded[name] for name in report.RUNTIME_FIELDS}
    value["identity_comparisons"].update(
        engine_files_equal=canonical(current["engine_files_sha256"])
        == canonical(recorded["engine_files_sha256"]),
        example_files_equal=canonical(current["example_files_sha256"])
        == canonical(recorded["example_files_sha256"]),
        runtime_fields_equal=canonical(runtime_current) == canonical(runtime_recorded),
    )
    return value


def literal_implementation(decision):
    return {
        "decision_consumer": copy.deepcopy(decision["implementation"]),
        "reference_files_sha256": {
            "reference/" + name: "c" * 64
            for name in ("__init__.py", "consumer.py", "one_round.py", "report.py")
        },
        "entrypoint_files_sha256": {"reference_episode.py": "d" * 64},
    }


def literal_evaluation(decision):
    """Invented values exercise admission, not the arithmetic model's correctness."""
    values = [Fraction(1, 4), Fraction(1, 2), Fraction(1, 2)]
    actions = []
    for index, (row, value) in enumerate(
        zip(decision["legal_actions"], values, strict=True)
    ):
        actions.append(
            {
                "action": {name: row[name] for name in ("card_idx", "target_idx")},
                "expected_value": {
                    "numerator": str(value.numerator),
                    "denominator": str(value.denominator),
                },
                "expected_value_float": float(value),
                "mass": {"numerator": "1", "denominator": "1"},
                "win_mass": {"numerator": "0", "denominator": "1"},
                "loss_mass": {"numerator": "0", "denominator": "1"},
                "ongoing_mass": {"numerator": "1", "denominator": "1"},
                "leaves": index + 2,
            }
        )
    return {
        "model": report.MODEL,
        "horizon_rounds": 1,
        "terminal_depth": 1,
        "probability_model": report.PROBABILITY_MODEL,
        "value_model": report.VALUE_MODEL,
        "actions": actions,
        "best_actions": [row["action"] for row in actions[1:]],
        "total_leaves": 9,
        "elapsed_seconds": 0.01,
    }


def literal_base(decision=None):
    decision = literal_decision() if decision is None else decision
    return report.reference_report_base(
        decision,
        canonical(decision) + b"\n",
        literal_implementation(decision),
        {"max_paths": 100, "max_total_paths": 1000, "max_seconds": 1},
    )


def literal_report(decision=None):
    decision = literal_decision() if decision is None else decision
    return report.complete_reference_report(
        literal_base(decision), literal_evaluation(decision)
    )


def replace(value, path, replacement):
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement


class ReferenceReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mcts-reference-reader-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.saved = self.directory / "private-source-name.json"
        self.value = literal_report()

    def save(self, value=None, path=None):
        saved = self.saved if path is None else path
        saved.write_bytes(canonical(self.value if value is None else value) + b"\n")
        return saved

    def test_exact_ties_and_same_statistics_losses_need_no_new_search(self):
        diagnostics = self.value["diagnostics"]
        self.assertEqual(
            diagnostics["recommendation"]["value_loss"],
            {"numerator": "1", "denominator": "4"},
        )
        self.assertEqual(
            diagnostics["same_statistics"]["mean_visits"], diagnostics["recommendation"]
        )
        robust = diagnostics["same_statistics"]["visits_mean"]
        self.assertEqual(robust["action"], {"card_idx": 0, "target_idx": None})
        self.assertEqual(robust["value_loss"], {"numerator": "0", "denominator": "1"})
        self.assertEqual(
            self.value["evaluation"]["best_actions"],
            [{"card_idx": 0, "target_idx": None}, {"card_idx": 1, "target_idx": None}],
        )
        self.assertTrue(diagnostics["comparison_eligibility"]["eligible"])
        self.assertFalse(self.value["new_search_performed"])

    def test_legacy_ties_and_no_work_choices_remain_unavailable(self):
        legacy = literal_report(literal_decision(version=1))
        self.assertIsNone(legacy["diagnostics"]["same_statistics"])
        no_work = literal_report(literal_decision(no_work=True))
        self.assertIsNone(no_work["diagnostics"]["recommendation"])
        self.assertEqual(
            no_work["diagnostics"]["same_statistics"],
            {"mean_visits": None, "visits_mean": None},
        )

    def test_captured_bytes_and_exact_literal_state_are_separately_bound(self):
        decision = literal_decision()
        captured = json.dumps(decision, indent=2).encode()
        base = report.reference_report_base(
            decision, captured, literal_implementation(decision), self.value["limits"]
        )
        self.assertEqual(
            base["source_report"]["sha256"], hashlib.sha256(captured).hexdigest()
        )
        self.assertEqual(
            base["source_report"]["canonical_sha256"],
            hashlib.sha256(canonical(decision)).hexdigest(),
        )
        state_digest = hashlib.sha256(canonical(decision["selected_state"])).hexdigest()
        self.assertEqual(base["selected_state_sha256"], state_digest)
        original = canonical(decision)
        base["decision_report"]["selected_state"]["hand"][0]["accuracy"] = 1.0
        self.assertNotEqual(canonical(base["decision_report"]), original)
        with self.assertRaises(EpisodeInputError):
            report.complete_reference_report(base, literal_evaluation(decision))
        with self.assertRaises(EpisodeInputError):
            report.reference_report_base(
                decision, b"{}", literal_implementation(decision), self.value["limits"]
            )

    def test_adverse_fraction_action_mass_tie_and_identity_claims_are_rejected(self):
        mutations = (
            (("evaluation", "actions", 0, "expected_value", "numerator"), 1),
            (("evaluation", "actions", 0, "expected_value", "numerator"), "01"),
            (("evaluation", "actions", 0, "expected_value", "numerator"), "-0"),
            (("evaluation", "actions", 0, "expected_value", "numerator"), "2"),
            (("evaluation", "actions", 0, "expected_value", "denominator"), "0"),
            (("evaluation", "actions", 0, "expected_value", "denominator"), "9" * 2049),
            (("evaluation", "actions", 0, "expected_value_float"), float("nan")),
            (("evaluation", "actions", 0, "expected_value_float"), 0.25000001),
            (("evaluation", "actions", 0, "mass", "numerator"), "0"),
            (("evaluation", "actions", 0, "ongoing_mass", "numerator"), "0"),
            (("evaluation", "actions", 1, "action", "card_idx"), True),
            (("evaluation", "actions", 1, "action", "target_idx"), 0),
            (("evaluation", "actions", 0, "leaves"), 101),
            (("evaluation", "best_actions"), [{"card_idx": 0, "target_idx": None}]),
            (("evaluation", "total_leaves"), 10),
            (("evaluation", "elapsed_seconds"), 1.000001),
            (("diagnostics", "recommendation", "reference_best"), True),
            (
                (
                    "diagnostics",
                    "same_statistics",
                    "visits_mean",
                    "value_loss",
                    "numerator",
                ),
                "1",
            ),
            (("identity_comparisons", "search_engine_files_equal"), False),
            (("reference_engine_files_sha256", "actions.py"), "a" * 64),
            (
                ("implementation", "reference_files_sha256"),
                {"reference/../report.py": "a" * 64},
            ),
            (("new_search_performed",), True),
        )
        for path, replacement in mutations:
            with self.subTest(path=path, replacement=replacement):
                value = copy.deepcopy(self.value)
                replace(value, path, replacement)
                with self.assertRaises(EpisodeInputError):
                    report.validate_reference_report(value)
        for branch in ((), ("evaluation",), ("evaluation", "actions", 0)):
            value = copy.deepcopy(self.value)
            target = value
            for key in branch:
                target = target[key]
            target["unexpected"] = 1
            with self.assertRaises(EpisodeInputError):
                report.validate_reference_report(value)
        omitted = copy.deepcopy(self.value)
        omitted["evaluation"]["actions"].pop()
        with self.assertRaises(EpisodeInputError):
            report.validate_reference_report(omitted)

    def test_complete_model_rejects_broader_roots_after_state_hashes_are_rebound(self):
        state = self.value["decision_report"]["selected_state"]
        mutations = (
            (("player", "pips"), 8),
            (("player", "power_pips"), 6),
            (("player", "hp"), 101),
            (("player", "blades"), state["player"]["blades"] * 5),
            (("player", "blades", 0, "value"), -0.1),
            (("player", "shields", 0, "value"), 0.1),
            (
                ("player", "dots"),
                [{"tick": 1_000_001, "rounds_left": 1, "element": "frost"}],
            ),
            (("player", "dots"), [{"tick": 1, "rounds_left": 0, "element": "frost"}]),
            (
                ("player", "dots"),
                [{"tick": 1, "rounds_left": 1, "element": "frost"}] * 5,
            ),
            (("player", "base_attack"), state["hand"][0]),
            (("hand", 0, "damage_max"), 151),
            (("hand", 0, "damage_min"), 1),
            (("hand", 0, "modifier"), 3),
            (("hand", 0, "dot_rounds"), 1),
            (("hand", 0, "card_type"), "damage"),
            (("hand", 0, "card_type"), "heal"),
            (("hand", 0, "card_type"), "blade"),
            (("enemies", 0, "hp"), 0),
            (("enemies", 0, "is_boss"), True),
            (("enemies",), state["enemies"] * 3),
            (("enemies",), [{**copy.deepcopy(state["enemies"][0]), "pips": 3}] * 2),
            (
                ("boss_rules",),
                [
                    {
                        "type": "punish_traps",
                        "parameters": {"damage": 1},
                        "description": "Synthetic excluded mechanic",
                    }
                ],
            ),
        )
        for path, replacement in mutations:
            with self.subTest(path=path):
                value = copy.deepcopy(self.value)
                decision = value["decision_report"]
                replace(decision["selected_state"], path, copy.deepcopy(replacement))
                value["source_report"]["canonical_sha256"] = hashlib.sha256(
                    canonical(decision)
                ).hexdigest()
                value["selected_state_sha256"] = hashlib.sha256(
                    canonical(decision["selected_state"])
                ).hexdigest()
                with self.assertRaises(EpisodeInputError):
                    report.validate_reference_report(value)

    def test_refusals_and_mismatched_engines_cannot_claim_complete_values(self):
        base = literal_base()
        for kind in report.REFUSAL_KINDS - {"horizon_mismatch"}:
            refused = report.refused_reference_report(
                base, kind, "Bounded fixture refusal"
            )
            self.assertIsNone(refused["evaluation"])
            self.assertIsNone(refused["diagnostics"])
            refused["evaluation"] = copy.deepcopy(self.value["evaluation"])
            with self.assertRaises(EpisodeInputError):
                report.validate_reference_report(refused)
        with self.assertRaises(EpisodeInputError):
            report.refused_reference_report(
                base, "horizon_mismatch", "Wrong fixture claim"
            )
        engine_files = base["implementation"]["decision_consumer"][
            "engine_files_sha256"
        ]
        engine_files["actions.py"] = "a" * 64
        base["identity_comparisons"] = report._comparisons(
            base["decision_report"], base["implementation"]
        )
        with self.assertRaises(EpisodeInputError):
            report.complete_reference_report(base, self.value["evaluation"])
        self.assertEqual(
            report.refused_reference_report(
                base, "engine_mismatch", "Qualified engine required"
            )["status"],
            "refused",
        )

    def test_passive_html_keeps_large_exact_strings_and_all_fragment_types(self):
        decision = literal_decision()
        evaluation = literal_evaluation(decision)
        exact = Fraction(2**80 + 1, 2**81)
        evaluation["actions"][1]["expected_value"] = report._fraction_object(exact)
        evaluation["actions"][1]["expected_value_float"] = float(exact)
        evaluation["best_actions"] = [evaluation["actions"][1]["action"]]
        value = report.complete_reference_report(literal_base(decision), evaluation)
        self.save(value)
        before = self.saved.read_bytes()
        with ExitStack() as stack:
            stack.enter_context(guarded_routes(no_search=True))
            stack.enter_context(
                patch.object(
                    episode_decision, "current_identity", side_effect=AssertionError
                )
            )
            stack.enter_context(
                patch.object(
                    episode_decision, "_reconstruct", side_effect=AssertionError
                )
            )
            stack.enter_context(
                patch.object(GameState, "heuristic_value", side_effect=AssertionError)
            )
            stack.enter_context(
                patch.object(random, "random", side_effect=AssertionError)
            )
            stack.enter_context(
                patch.object(random, "randint", side_effect=AssertionError)
            )
            stack.enter_context(
                patch.object(subprocess, "Popen", side_effect=AssertionError)
            )
            stack.enter_context(patch.dict(sys.modules, {"reference.one_round": None}))
            for appearance in ("obscur", "clair"):
                output = report.reference_inspection_html(self.saved, appearance)
                artifact = Artifact(output)
                self.assertEqual(artifact.fragments["/evaluation"], value["evaluation"])
                self.assertEqual(
                    artifact.fragments["/diagnostics"], value["diagnostics"]
                )
                self.assertIn(str(exact.numerator).encode(), output)
                self.assertIn(str(exact.denominator).encode(), output)
                self.assertIn(b"not lost win probability", output)
                self.assertNotIn(b"<script", output)
                self.assertNotIn(b"<iframe", output)
                self.assertNotIn(self.saved.name.encode(), output)
                self.assertTrue(output.endswith(b"</html>\n"))
                self.assertTrue(
                    all(link[1:] in artifact.ids for link in artifact.links)
                )
        self.assertEqual(self.saved.read_bytes(), before)

    def test_comparison_discloses_limits_and_refuses_incompatible_state_rankings(self):
        left = self.save()
        right_value = copy.deepcopy(self.value)
        right_value["limits"]["max_seconds"] = 2
        right = self.save(right_value, self.directory / "right.json")
        with guarded_routes(no_search=True):
            compatible = report.reference_comparison_html(left, right)
        self.assertIn(b"equal exact one-round value loss", compatible)
        self.assertIn(b"Operational limits equal", compatible)
        right_value = report.refused_reference_report(
            literal_base(), "work_limit", "Fixture cap"
        )
        self.save(right_value, right)
        with guarded_routes(no_search=True):
            refused = report.reference_comparison_html(left, right)
        self.assertIn(b"No winner is declared", refused)
        self.assertNotIn(b"has lower exact one-round value loss", refused)
        changed = literal_decision()
        changed["selected_state"]["player"]["hp"] -= 1
        self.save(literal_report(changed), right)
        incompatible = report.reference_comparison_html(left, right)
        self.assertIn(b"exact_saved_states_differ", incompatible)
        self.assertIn(b"No winner is declared", incompatible)

    def test_duplicate_keys_appearance_and_excess_bytes_are_input_errors(self):
        for data in (b'{"format":1,"format":2}', b"\xff", b"{", b""):
            self.saved.write_bytes(data)
            with self.assertRaises(EpisodeInputError):
                report.reference_inspection_html(self.saved)
        self.save()
        with self.assertRaises(EpisodeInputError):
            report.reference_inspection_html(self.saved, "auto")
        with patch("game.episode_record.RECORD_BYTES", 8):
            with self.assertRaisesRegex(EpisodeInputError, "exceeds 8 bytes"):
                report.reference_inspection_html(self.saved)


if __name__ == "__main__":
    unittest.main()
