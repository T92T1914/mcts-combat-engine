"""Passive rendering preserves admitted values without environment or search work."""
import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import inspect_episode
from game import episode_inspection as inspection
from game import episode_record as records

ROOT = Path(__file__).resolve().parent.parent


def synthetic_record():
    """A literal schema fixture, not evidence of actual recording or replay."""
    pulse = {
        "name": "Duplicate", "element": "ember", "card_type": "damage",
        "pip_cost": 0, "accuracy": 1.0, "damage_min": 20, "damage_max": 30,
        "heal": 0, "dot_tick": 2, "dot_rounds": 2, "modifier": 0.0,
        "hits_all": False,
    }
    other = {**pulse, "name": "Shifted", "card_type": "utility", "accuracy": 1}
    player = {
        "name": "Operator", "element": "ember", "hp": 90, "max_hp": 100,
        "pips": 2, "power_pips": 1, "power_pip_chance": 0.4,
        "resist": {"frost": 0.0}, "boost": {"ember": 0},
        "blades": [{"value": 0.2, "element": "ember"}],
        "traps": [], "shields": [{"value": -0.5, "element": "neutral"}],
        "dots": [{"tick": 10**60 + 7, "rounds_left": 2, "element": "frost"}],
        "is_boss": False, "base_attack": None, "policy": None,
    }
    dead = {**copy.deepcopy(player), "name": "Retained dead slot", "hp": 0}
    enemy = {**copy.deepcopy(player), "name": "Target", "element": "frost",
             "hp": 70, "is_boss": True, "base_attack": copy.deepcopy(pulse)}
    state = {
        "player": player, "enemies": [dead, enemy], "hand": [pulse, other],
        "round_num": 1, "boss_rules": [
            {"type": "punish_traps", "parameters": {"damage": 10},
             "description": "Stored rule description"},
            {"type": "enrage_below_half", "parameters": {"blade": 0.2},
             "description": "Stored second rule description"},
        ],
    }
    first = copy.deepcopy(state)
    first["hand"] = [copy.deepcopy(other), copy.deepcopy(pulse), copy.deepcopy(pulse)]
    second = copy.deepcopy(first)
    second["round_num"] = 2
    second["hand"] = [copy.deepcopy(pulse), copy.deepcopy(pulse)]
    final = copy.deepcopy(second)
    final["round_num"] = 3
    final["hand"] = [copy.deepcopy(pulse) for _ in range(6)]
    digest = "a" * 64
    return {
        "format": "mcts-episode-record", "schema_version": 1,
        "content": {"kind": "custom",
                    "cards": {"bytes": 123, "sha256": digest},
                    "scenarios": {"bytes": 456, "sha256": digest}},
        "scenario": {"name": "Synthetic trial", "environment_seed": 7,
                     "deck": [copy.deepcopy(pulse), copy.deepcopy(other),
                              copy.deepcopy(pulse)]},
        "initial_state": state,
        "implementation": {
            "python": "3.11", "python_implementation": "Stored interpreter",
            "platform": "Stored platform", "engine_import_kind": "site-packages",
            "distribution_version": None, "distribution_matches_import": False,
            "engine_files_sha256": {"engine/state.py": digest},
            "example_files_sha256": {"game/runner.py": digest},
            "entrypoint_files_sha256": {"episode.py": digest},
            "machine": "Stored machine", "pointer_bits": 64,
            "python_full_version": "Stored full version", "python_build": ["", ""],
            "python_cache_tag": None, "rng_state_version": 3,
        },
        "configuration": {
            "method": "mcts", "mode": "serial_clockless", "search_seed": 11,
            "search_rng_mode": "seed_once_continue", "max_rounds": 2,
            "max_sims_per_decision": 8, "horizon_rounds": 1,
            "max_transitions_per_decision": 8, "exploration": 1.2,
            "time_budget_ms": None, "parallel": False, "workers": None,
            "priors": None,
            "policy_rng": {"scheme": "policy-v1", "seed": 0, "used_by_policy": False},
        },
        "environment_rng": {
            "checkpoint_scheme": "python-random-getstate-json-v1", "state_version": 3,
            "after_scenario_sha256": digest, "final_sha256": "b" * 64,
        },
        "steps": [
            {"index": 0, "round_num": 1, "state": first,
             "action": {"card_idx": 0, "target_idx": 1, "label": "Stored first"}},
            {"index": 1, "round_num": 2, "state": second,
             "action": {"card_idx": 1, "target_idx": 0, "label": "Stored second"}},
        ],
        "final": {"state": final, "score": 0.12345678901234568,
                  "terminal_result": None, "rounds": 2, "termination": "round_limit"},
    }


class Artifact(HTMLParser):
    """Read authoritative fragments and structural references from actual HTML."""

    def __init__(self, data):
        super().__init__(convert_charrefs=True)
        self.fragments = {}
        self.order = []
        self.active = None
        self.text = []
        self.step_count = None
        self.links = []
        self.ids = []
        self.tags = []
        self.attributes = []
        self.feed(data.decode("utf-8"))

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.tags.append(tag)
        self.attributes.extend(attrs)
        if "id" in attributes:
            self.ids.append(attributes["id"])
        if tag == "a":
            self.links.append(attributes["href"])
        if tag == "section" and attributes.get("data-json-pointer") == "/steps":
            self.step_count = int(attributes["data-step-count"])
        if tag == "pre":
            self.active = attributes["data-json-pointer"]
            self.order.append(self.active)
            self.text = []

    def handle_data(self, data):
        if self.active is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "pre":
            if self.active in self.fragments:
                raise AssertionError("duplicate authoritative fragment")
            self.fragments[self.active] = json.loads("".join(self.text))
            self.active = None

    def record(self):
        value = {pointer[1:]: item for pointer, item in self.fragments.items()
                 if not pointer.startswith("/steps/")}
        value["steps"] = [self.fragments[f"/steps/{index}"]
                          for index in range(self.step_count)]
        return value


def forbidden(*args, **kwargs):
    raise AssertionError("unexpected environment, compatibility or search work")


class InspectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-inspection-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.saved = self.directory / "private-source-name.json"
        self.value = synthetic_record()
        self.save()

    def save(self):
        self.saved.write_bytes(json.dumps(self.value, ensure_ascii=True,
                                         indent=1, allow_nan=False).encode("utf-8"))

    def cli(self, *arguments):
        out, err = io.BytesIO(), io.StringIO()
        text_out = io.TextIOWrapper(out, encoding="utf-8", newline="\r\n",
                                   write_through=True)
        with contextlib.redirect_stdout(text_out), contextlib.redirect_stderr(err):
            try:
                status = inspect_episode.main(list(arguments))
            except SystemExit as exc:
                status = exc.code
        return status, out.getvalue(), err.getvalue()

    def test_complete_typed_fragments_preserve_both_editions_and_input(self):
        original = self.saved.read_bytes()
        expected = records.canonical(self.value)
        for appearance in ("obscur", "clair"):
            with self.subTest(appearance=appearance):
                output = inspection.inspection_html(self.saved, appearance=appearance)
                artifact = Artifact(output)
                self.assertEqual(records.canonical(artifact.record()), expected)
                self.assertEqual(len(artifact.fragments), 9 + len(self.value["steps"]))
                self.assertEqual([p for p in artifact.order if p.startswith("/steps/")],
                                 ["/steps/0", "/steps/1"])
                self.assertEqual(artifact.step_count, 2)
                self.assertIn(str(10**60 + 7).encode(), output)
                self.assertIn(b"0.12345678901234568", output)
                self.assertIn(hashlib.sha256(original).hexdigest().encode(), output)
                self.assertNotIn(self.saved.name.encode(), output)
                self.assertEqual(output[-2:], b">\n")
                self.assertNotIn(b"\r\n", output)
        self.assertEqual(self.saved.read_bytes(), original)

    def test_boundary_and_action_references_use_same_step_without_compacting(self):
        output = inspection.inspection_html(self.saved).decode()
        first = output.split('<article id="step-0">')[1].split("</article>")[0]
        second = output.split('<article id="step-1">')[1].split("</article>")[0]
        first_reference = first.split("<dt>Card reference</dt>")[1].split("</dd>")[0]
        second_reference = second.split("<dt>Enemy reference</dt>")[1].split("</dd>")[0]
        self.assertIn("Shifted", first_reference)
        self.assertNotIn("Duplicate", first_reference)
        self.assertIn("Retained dead slot", second_reference)
        self.assertIn("after refill, before recorded action", first)
        self.assertIn("before the runner's first refill", output)
        self.assertIn("without another decision refill", output)
        self.assertIn("not a calibrated win probability", output)
        final_hand = Artifact(output.encode()).record()["final"]["state"]["hand"]
        self.assertEqual(len(final_hand), 6)

    def test_null_and_unresolved_indices_retain_stored_label(self):
        self.value["steps"][0]["action"] = {
            "card_idx": None, "target_idx": 7, "label": "Keep literal label"}
        self.value["steps"][1]["action"]["card_idx"] = 6
        self.save()
        output = inspection.inspection_html(self.saved)
        self.assertIn(b"<code>null</code> (stored index)", output)
        self.assertIn(b"no entry at this index in the stored enemy slots", output)
        self.assertIn(b"no entry at this index in the stored hand", output)
        self.assertIn(b"Keep literal label", output)
        self.assertEqual(records.canonical(Artifact(output).record()),
                         records.canonical(self.value))

    def test_zero_step_terminal_is_distinct_from_round_limit(self):
        self.value["steps"] = []
        final = self.value["final"]
        final.update({"state": copy.deepcopy(self.value["initial_state"]),
                      "score": 0.0, "terminal_result": 0.0, "rounds": 0,
                      "termination": "terminal"})
        final["state"]["player"]["hp"] = 0
        self.save()
        output = inspection.inspection_html(self.saved)
        self.assertIn(b"No recorded decisions. Stored steps: <code>[]</code>", output)
        self.assertNotIn(b'<article id="step-', output)
        self.assertEqual(Artifact(output).step_count, 0)
        self.assertEqual(records.canonical(Artifact(output).record()),
                         records.canonical(self.value))

    def test_untrusted_markup_controls_urls_and_long_fields_stay_text(self):
        hostile = '</pre><script src="https://example.invalid/x">&\"\n\x00'
        self.value["scenario"]["name"] = hostile
        self.value["steps"][0]["action"]["label"] = hostile
        self.value["initial_state"]["player"]["name"] = hostile
        self.value["implementation"]["python_full_version"] = hostile + "x" * 1900
        self.value["implementation"]["example_files_sha256"] = {
            'stored/<img src="x">.py': "c" * 64}
        self.save()
        output = inspection.inspection_html(self.saved)
        artifact = Artifact(output)
        self.assertEqual(records.canonical(artifact.record()),
                         records.canonical(self.value))
        self.assertFalse(set(artifact.tags) & {"script", "iframe", "form", "img",
                                             "object", "link"})
        self.assertTrue(all(link.startswith("#") for link in artifact.links))
        self.assertTrue(all(link[1:] in artifact.ids for link in artifact.links))
        self.assertEqual(len(artifact.ids), len(set(artifact.ids)))
        self.assertTrue(all(not name.startswith("on")
                            for name, _ in artifact.attributes))
        self.assertTrue(all("example.invalid" not in (value or "")
                            for _, value in artifact.attributes))
        self.assertIn(b"\\u0000", output)
        self.assertIn(b"overflow-wrap:anywhere", output)

    def test_admission_only_reads_once_and_never_performs_work(self):
        names = ("load_content", "load_snapshot", "observed_identity",
                 "implementation_identity", "_record_owner", "record_episode",
                 "replay_episode", "play_game", "is_legal_action", "legal_actions")
        with contextlib.ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(records, name, forbidden))
            for name in ("Action", "Card", "Combatant", "GameState", "Charm", "DoT"):
                stack.enter_context(patch.object(getattr(records, name), "__init__",
                                                forbidden))
            stack.enter_context(patch.object(records.random, "Random", forbidden))
            captured = stack.enter_context(patch.object(records, "_read",
                                                        wraps=records._read))
            output = inspection.inspection_html(self.saved)
        captured.assert_called_once_with(self.saved, "record", records.RECORD_BYTES)
        self.assertEqual(records.canonical(Artifact(output).record()),
                         records.canonical(self.value))

    def test_stored_runtime_labels_need_no_local_compatibility(self):
        self.value["implementation"].update({"python": "Stored alternative",
                                             "platform": "Unrelated saved host"})
        self.save()
        with patch.object(records, "observed_identity", forbidden):
            output = inspection.inspection_html(self.saved)
        self.assertIn(b"Stored alternative", output)
        self.assertIn(b"Unrelated saved host", output)

    def test_presentation_roles_pin_and_all_local_faces_match_accepted_adapter(self):
        wrapper = json.loads((ROOT / "presentation/tokens.json").read_text())
        for key, expected in inspection.PRESENTATION_SOURCE.items():
            self.assertEqual(wrapper["source"][key], expected)
        for appearance, roles in inspection.THEMES.items():
            for name, color in roles.items():
                self.assertEqual(wrapper["themes"][appearance][name], color)
        from tools.presentation import FACES

        self.assertEqual(inspection.FACES, FACES)
        output = inspection.inspection_html(self.saved).decode()
        for weight, style, full, postscript in FACES:
            declaration = (f'src:local("{full}"),local("{postscript}");'
                           f'font-weight:{weight};font-style:{style};')
            self.assertIn(declaration, output)
        self.assertIn('font-family:"MCTS Episode Inter",Arial,sans-serif', output)
        self.assertIn("font-synthesis:none", output)
        self.assertNotIn("url(", output)
        self.assertNotIn("prefers-color-scheme", output)
        self.assertIn("@media(forced-colors:active)", output)
        self.assertIn("@media print", output)

    def test_output_limit_includes_lf_and_refuses_admitted_record_before_stdout(self):
        output = inspection.inspection_html(self.saved)
        with patch.object(inspection, "HTML_BYTES", len(output)):
            self.assertEqual(inspection.inspection_html(self.saved), output)
        with patch.object(inspection, "HTML_BYTES", len(output) - 1):
            status, out, err = self.cli(str(self.saved))
        self.assertEqual(status, 1)
        self.assertEqual(out, b"")
        self.assertIn("including final LF", err)
        self.assertTrue(err.startswith("episode inspection:"))

    def test_invalid_appearance_and_record_are_input_errors_with_empty_stdout(self):
        with self.assertRaises(records.EpisodeInputError):
            inspection.inspection_html(self.saved, appearance="auto")
        status, out, _ = self.cli(str(self.saved), "--appearance", "auto")
        self.assertEqual((status, out), (2, b""))
        for malformed in (b'{"format":1,"format":2}', b"\xff", b"{",
                          b'{"schema_version":true}'):
            with self.subTest(malformed=malformed):
                self.saved.write_bytes(malformed)
                status, out, err = self.cli(str(self.saved))
                self.assertEqual((status, out), (2, b""))
                self.assertIn("error:", err)
        status, out, _ = self.cli(str(self.directory / "absent.json"))
        self.assertEqual((status, out), (2, b""))

    def test_limit_plus_one_read_refuses_before_parse_or_work(self):
        with patch.object(records, "RECORD_BYTES", 8), \
                patch.object(records, "_parse", forbidden):
            status, out, err = self.cli(str(self.saved))
        self.assertEqual((status, out), (2, b""))
        self.assertIn("exceeds 8 bytes", err)

    def test_runtime_failure_interrupt_and_failed_sink_have_correct_phases(self):
        for failure, status in ((MemoryError("fixture resource refusal"), 1),
                                (KeyboardInterrupt(), 130)):
            with self.subTest(status=status), patch.object(
                    inspect_episode, "inspection_html", side_effect=failure):
                actual, out, err = self.cli(str(self.saved))
            self.assertEqual((actual, out), (status, b""))
            self.assertIn("episode inspection:", err)
        class FailedSink:
            buffer = None

            def __init__(self):
                self.buffer = self

            def write(self, data):
                raise OSError("fixture closed output sink")

        err = io.StringIO()
        with contextlib.redirect_stdout(FailedSink()), contextlib.redirect_stderr(err):
            self.assertEqual(inspect_episode.main([str(self.saved)]), 1)
        self.assertIn("fixture closed output sink", err.getvalue())

    def test_flush_refusal_keeps_actual_process_exit_one_through_shutdown(self):
        entry = ROOT / "inspect_episode.py"
        wrapper = f'''
import io
import runpy
import sys

class RefusedFlush(io.BufferedWriter):
    def flush(self):
        raise OSError("fixture stdout flush refusal")

sys.path.insert(0, {str(ROOT)!r})
raw = io.FileIO(sys.stdout.fileno(), "wb", closefd=False)
sys.stdout = io.TextIOWrapper(RefusedFlush(raw), encoding="utf-8")
sys.argv = [{str(entry)!r}, {str(self.saved)!r}]
runpy.run_path({str(entry)!r}, run_name="__main__")
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", "-c", wrapper], cwd=self.directory,
            env=environment, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(b"episode inspection: fixture stdout flush refusal",
                      result.stderr)
        self.assertNotIn(b"Exception ignored", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_actual_command_emits_binary_lf_and_identical_typed_record(self):
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "inspect_episode.py"), str(self.saved)],
            cwd=self.directory, env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assertTrue(result.stdout.endswith(b"</html>\n"))
        self.assertNotIn(b"\r\n", result.stdout)
        self.assertEqual(records.canonical(Artifact(result.stdout).record()),
                         records.canonical(self.value))

    def test_default_episode_bytes_match_actual_pre_edit_baseline(self):
        captured = self.saved.read_bytes()
        self.assertEqual(len(captured), 17834)
        self.assertEqual(
            hashlib.sha256(captured).hexdigest(),
            "04a08dd904b0d7d25e9a434211f468f1cfaaf40d849c2c2a9d922fa6f7459c94",
        )
        output = inspection.inspection_html(self.saved)
        self.assertEqual(len(output), 42407)
        self.assertEqual(
            hashlib.sha256(output).hexdigest(),
            "f83c85473ff57ff0e2428b047bbdd0ddfcc86393bb8cf2a09dda7dd6dbaded91",
        )


def synthetic_decision_report(*, zero=False):
    """Literal saved-report representation, never a search or producer invocation."""
    episode = synthetic_record()
    state = copy.deepcopy(episode["steps"][0]["state"])
    state["hand"] = [copy.deepcopy(state["hand"][1]) for _ in range(7)]
    implementation = copy.deepcopy(episode["implementation"])
    implementation["entrypoint_files_sha256"] = {"decide_episode.py": "d" * 64}
    implementation["platform"] = "Different saved producer host"
    alternatives = []
    for index in range(8):
        sampled = index in (0, 2, 4, 7) and not zero
        value = {0: -0.0, 2: 1.25, 4: 1, 7: 10**60 + 7}.get(index, 0)
        alternatives.append({
            "card_idx": None if index == 0 else index - 1,
            "target_idx": None if index == 0 else 1,
            "label": "Literal Pass label" if index == 0 else "Duplicate saved label",
            "status": "sampled" if sampled else "unvisited",
            "visits": 1 if sampled else 0,
            "value_sum": value if sampled else (-0.0 if index == 0 else 0),
            "mean_shaped_reward": value / 1 if sampled else None,
        })
    ranking = [{name: alternatives[index][name] for name in ("card_idx", "target_idx")}
               for index in (7, 0, 4, 2)] if not zero else []
    return {
        "format": "mcts-episode-decision-report", "schema_version": 1,
        "status": "no_work" if zero else "decision", "search_performed": not zero,
        "source_record": {"bytes": 1234, "sha256": "e" * 64},
        "selection": {"step_index": 0, "round_num": 1,
                      "state_pointer": "/steps/0/state"},
        "selected_state": state,
        "stored_action": {"card_idx": None, "target_idx": 7,
                          "label": "Literal old action"},
        "stored_provenance": {name: copy.deepcopy(episode[name]) for name in (
            "content", "scenario", "configuration", "implementation",
            "environment_rng")},
        "implementation": implementation,
        "identity_comparisons": {
            "engine_files_equal": False, "example_files_equal": True,
            "runtime_fields_equal": False,
            "entrypoint_roles": {"recorded": "episode.py",
                                 "current": "decide_episode.py", "same_role": False},
        },
        "value_semantics": "Saved shaped rewards, not calibrated probabilities.",
        "configuration": {
            "method": "mcts", "mode": "serial_clockless", "seed": -19,
            "search_rng_mode": "new_seed_per_decision", "max_sims": 0 if zero else 4,
            "horizon_rounds": 2, "max_transitions": 0 if zero else 8,
            "exploration": 1.2, "time_budget_ms": None, "priors": None,
            "parallel": False, "workers": None,
        },
        "work": {"simulations": 0 if zero else 4, "transitions": 0 if zero else 8,
                 "unused_transitions": 0,
                 "stop_reasons": ["zero_requested_simulations"] if zero else [
                     "transition_allowance", "simulation_cap"]},
        "elapsed_seconds": 0.0 if zero else 0.25,
        "legal_actions": alternatives, "ranking": ranking,
        "recommendation": None if zero else {
            **ranking[0], "label": alternatives[7]["label"]},
    }


def report_fragments(output):
    return {pointer[1:]: value for pointer, value in Artifact(output).fragments.items()}


def replace_leaf(value, path, replacement):
    target = value
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement


class DecisionInspectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-decision-inspection-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.saved = self.directory / "private-decision-name.json"
        self.value = synthetic_decision_report()
        self.save()

    save = InspectionTests.save
    cli = InspectionTests.cli

    def test_all_eighteen_typed_fragments_and_input_bytes_in_both_editions(self):
        original = self.saved.read_bytes()
        for appearance in ("obscur", "clair"):
            with self.subTest(appearance=appearance):
                output = inspection.decision_inspection_html(
                    self.saved, appearance=appearance)
                artifact = Artifact(output)
                self.assertEqual(set(artifact.fragments),
                                 {"/" + name for name in inspection.DECISION_FIELDS})
                self.assertEqual(len(artifact.order), 18)
                self.assertEqual(records.canonical(report_fragments(output)),
                                 records.canonical(self.value))
                self.assertIn(str(10**60 + 7).encode(), output)
                self.assertIn(b"-0.0", output)
                self.assertIn(hashlib.sha256(original).hexdigest().encode(), output)
                self.assertIn(b"Captured decision report SHA-256", output)
                self.assertIn(b"Claimed original episode SHA-256", output)
                self.assertNotIn(self.saved.name.encode(), output)
                self.assertNotIn(str(self.directory).encode(), output)
                self.assertTrue(output.endswith(b"</html>\n"))
                self.assertNotIn(b"\r\n", output)
        self.assertEqual(self.saved.read_bytes(), original)

    def test_slots_unresolved_references_and_raw_ranking_are_not_repaired(self):
        output = inspection.decision_inspection_html(self.saved)
        facts = report_fragments(output)
        self.assertEqual(len(facts["selected_state"]["hand"]), 7)
        self.assertEqual(facts["selected_state"]["enemies"][0]["hp"], 0)
        self.assertEqual(facts["stored_action"]["target_idx"], 7)
        self.assertIn(b"no entry at this index in the stored enemy slots", output)
        self.assertEqual(facts["ranking"], self.value["ranking"])
        self.value["selected_state"]["hand"] = self.value["selected_state"]["hand"][:2]
        self.value["legal_actions"][6]["target_idx"] = 7
        self.save()
        output = inspection.decision_inspection_html(self.saved)
        self.assertIn(b"no entry at this index in the stored hand", output)
        self.assertIn(b"no entry at this index in the stored enemy slots", output)
        self.assertEqual(records.canonical(report_fragments(output)),
                         records.canonical(self.value))

    def test_pass_object_null_recommendation_and_self_target_stay_distinct(self):
        self.value["ranking"] = [
            {"card_idx": None, "target_idx": None},
            *self.value["ranking"][:1], *self.value["ranking"][2:],
        ]
        self.value["recommendation"] = {
            "card_idx": None, "target_idx": None, "label": "Literal Pass label"}
        self.value["legal_actions"][1]["target_idx"] = None
        self.save()
        positive = inspection.decision_inspection_html(self.saved)
        self.assertEqual(report_fragments(positive)["recommendation"],
                         self.value["recommendation"])
        self.assertIn(b"Reported recommendation object", positive)
        self.assertNotIn(b"No recorded recommendation:", positive)
        self.value = synthetic_decision_report(zero=True)
        self.value["elapsed_seconds"] = -0.0
        self.save()
        zero = inspection.decision_inspection_html(self.saved, appearance="clair")
        self.assertIsNone(report_fragments(zero)["recommendation"])
        self.assertEqual(report_fragments(zero)["ranking"], [])
        self.assertIn(b"No recorded recommendation: <code>null</code>", zero)
        self.assertIn(b"Zero requested simulations", zero)
        self.assertIn(b"-0.0", zero)

    def test_saved_runtime_maps_and_comparison_claims_do_not_become_observations(self):
        self.value["implementation"].update({
            "python": "Another saved version", "python_cache_tag": "Other cache",
            "distribution_version": None, "distribution_matches_import": False,
            "engine_files_sha256": {"other-engine.py": "f" * 64},
        })
        self.value["stored_provenance"]["implementation"]["example_files_sha256"] = {
            "historical/demo.py": "b" * 64}
        self.value["identity_comparisons"]["engine_files_equal"] = True
        self.save()
        with patch.object(records, "observed_identity", forbidden), \
                patch.object(records, "implementation_identity", forbidden):
            output = inspection.decision_inspection_html(self.saved)
        self.assertIn(b"Another saved version", output)
        self.assertIn(b"historical/demo.py", output)
        self.assertEqual(records.canonical(report_fragments(output)),
                         records.canonical(self.value))

    def test_hostile_fields_are_escaped_with_only_fixed_local_navigation(self):
        hostile = '</pre><script src="https://example.invalid/x">&\"\n\x00'
        self.value["value_semantics"] = hostile
        self.value["stored_action"]["label"] = hostile
        self.value["selected_state"]["player"]["name"] = hostile
        self.value["implementation"]["example_files_sha256"] = {
            'game/<img src="x">.py': "c" * 64}
        self.save()
        output = inspection.decision_inspection_html(self.saved)
        artifact = Artifact(output)
        self.assertEqual(records.canonical(report_fragments(output)),
                         records.canonical(self.value))
        self.assertFalse(set(artifact.tags) & {"script", "iframe", "form", "img",
                                             "object", "link"})
        self.assertTrue(all(link.startswith("#") for link in artifact.links))
        self.assertTrue(all(link[1:] in artifact.ids for link in artifact.links))
        self.assertEqual(len(artifact.ids), len(set(artifact.ids)))
        self.assertTrue(all(not name.startswith("on")
                            for name, _ in artifact.attributes))
        self.assertTrue(all("example.invalid" not in (value or "")
                            for _, value in artifact.attributes))
        self.assertIn(b"\\u0000", output)
        self.assertIn(b"font-synthesis:none", output)
        self.assertNotIn(b"url(", output)

    def test_read_parse_and_validator_are_passive_and_use_one_capture(self):
        names = (
            "load_content", "load_snapshot", "observed_identity",
            "implementation_identity", "_record_owner", "record_episode",
            "replay_episode", "play_game", "is_legal_action", "legal_actions",
            "normalized", "rng_digest",
        )
        with contextlib.ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(records, name, forbidden))
            for name in ("Action", "Card", "Combatant", "GameState", "Charm", "DoT"):
                stack.enter_context(patch.object(getattr(records, name), "__init__",
                                                forbidden))
            stack.enter_context(patch.object(records.random, "Random", forbidden))
            stack.enter_context(patch.dict(
                sys.modules, {"game.episode_decision": None}))
            read = stack.enter_context(patch.object(records, "_read",
                                                    wraps=records._read))
            parse = stack.enter_context(patch.object(records, "_parse",
                                                     wraps=records._parse))
            validate = stack.enter_context(patch.object(
                inspection, "validate_decision_report",
                wraps=inspection.validate_decision_report))
            output = inspection.decision_inspection_html(self.saved)
        read.assert_called_once_with(self.saved, "decision report",
                                     records.RECORD_BYTES)
        parse.assert_called_once_with(self.saved.read_bytes(), "decision report",
                                      200_000, 10**300)
        validate.assert_called_once()
        self.assertEqual(records.canonical(report_fragments(output)),
                         records.canonical(self.value))

    def test_digest_and_rendering_use_captured_buffer_after_input_changes(self):
        captured = self.saved.read_bytes()
        def read_then_change(*args):
            self.saved.write_bytes(b"changed after capture")
            return captured
        with patch.object(records, "_read", side_effect=read_then_change) as read:
            output = inspection.decision_inspection_html(self.saved)
        read.assert_called_once()
        self.assertIn(hashlib.sha256(captured).hexdigest().encode(), output)
        self.assertEqual(records.canonical(report_fragments(output)),
                         records.canonical(self.value))

    def test_strict_shapes_kinds_roles_and_bounds_refuse_before_output(self):
        cases = (
            (("format",), "mcts-decision-report", "/format"),
            (("schema_version",), True, "/schema_version"),
            (("source_record", "bytes"), 0, "/source_record/bytes"),
            (("source_record", "sha256"), "A" * 64, "/source_record/sha256"),
            (("selection", "step_index"), True, "/selection/step_index"),
            (("selection", "round_num"), 2, "/selection/round_num"),
            (("selection", "state_pointer"), "/steps/0/action",
             "/selection/state_pointer"),
            (("selected_state", "round_num"), 2, "/selected_state/round_num"),
            (("selected_state", "hand", 0, "accuracy"), 0, "/selected_state"),
            (("stored_action", "card_idx"), 7, "/stored_action/card_idx"),
            (("stored_provenance", "configuration", "max_rounds"), 0,
             "/stored_provenance/configuration"),
            (("stored_provenance", "implementation", "entrypoint_files_sha256"),
             {"decide_episode.py": "a" * 64}, "/stored_provenance/implementation"),
            (("implementation", "entrypoint_files_sha256"), {"episode.py": "a" * 64},
             "/implementation/entrypoint_files_sha256"),
            (("implementation", "example_files_sha256"), {"demo.py": "a" * 64},
             "/implementation/example_files_sha256"),
            (("implementation", "engine_files_sha256"), {"../bad": "a" * 64},
             "/implementation/engine_files_sha256"),
            (("implementation", "pointer_bits"), 48, "/implementation/pointer_bits"),
            (("identity_comparisons", "engine_files_equal"), 1,
             "/identity_comparisons/engine_files_equal"),
            (("identity_comparisons", "entrypoint_roles", "same_role"), True,
             "/identity_comparisons/entrypoint_roles/same_role"),
            (("configuration", "seed"), 2**63, "/configuration/seed"),
            (("configuration", "max_sims"), True, "/configuration/max_sims"),
            (("configuration", "max_transitions"), 7, "/configuration/max_transitions"),
            (("configuration", "parallel"), 0, "/configuration/parallel"),
            (("configuration", "workers"), 1, "/configuration/workers"),
            (("elapsed_seconds",), -1, "/elapsed_seconds"),
            (("legal_actions", 1, "card_idx"), None, "/legal_actions/1"),
            (("legal_actions", 0, "label"), "", "/legal_actions/0/label"),
        )
        baseline = copy.deepcopy(self.value)
        for path, replacement, location in cases:
            with self.subTest(path=path):
                self.value = copy.deepcopy(baseline)
                replace_leaf(self.value, path, replacement)
                self.save()
                status, out, err = self.cli(str(self.saved), "--decision-report")
                self.assertEqual((status, out), (2, b""))
                self.assertIn(location, err)
        for name, change in (
            ("extra root", lambda value: value.update({"unsupported": 1})),
            ("missing branch", lambda value: value.pop("stored_provenance")),
            ("extra row", lambda value: value["legal_actions"][0].update({"x": 1})),
        ):
            with self.subTest(name=name):
                self.value = copy.deepcopy(baseline)
                change(self.value)
                self.save()
                status, out, _ = self.cli(str(self.saved), "--decision-report")
                self.assertEqual((status, out), (2, b""))

    def test_positive_statistics_consistency_refusals_are_not_legality_checks(self):
        cases = (
            (("legal_actions", 1, "value_sum"), 1),
            (("legal_actions", 1, "mean_shaped_reward"), 0.0),
            (("legal_actions", 0, "visits"), 0),
            (("legal_actions", 2, "mean_shaped_reward"), 1.2500000000000002),
            (("legal_actions", 0, "mean_shaped_reward"), False),
            (("work", "simulations"), 3),
            (("work", "transitions"), 9),
            (("work", "unused_transitions"), 1),
            (("work", "stop_reasons"), ["simulation_cap", "simulation_cap"]),
            (("work", "stop_reasons"), ["zero_requested_simulations"]),
            (("status",), "no_work"),
            (("search_performed",), False),
            (("ranking",), []),
            (("ranking",), [{"card_idx": None, "target_idx": None}] * 4),
            (("ranking", 0), {"card_idx": None, "target_idx": 1}),
            (("ranking", 0), {"card_idx": 0, "target_idx": 0}),
            (("legal_actions", 1), copy.deepcopy(self.value["legal_actions"][0])),
            (("recommendation",), None),
            (("recommendation", "label"), "changed recommendation label"),
        )
        baseline = copy.deepcopy(self.value)
        for path, replacement in cases:
            with self.subTest(path=path, replacement=replacement):
                self.value = copy.deepcopy(baseline)
                replace_leaf(self.value, path, replacement)
                self.save()
                status, out, err = self.cli(str(self.saved), "--decision-report")
                self.assertEqual((status, out), (2, b""))
                self.assertIn("error:", err)
        self.value = copy.deepcopy(baseline)
        self.value["work"]["stop_reasons"] = []
        self.save()
        self.assertEqual(records.canonical(report_fragments(
            inspection.decision_inspection_html(self.saved))),
            records.canonical(self.value))

    def test_zero_work_consistency_preserves_raw_zero_and_refuses_positive_claims(self):
        baseline = synthetic_decision_report(zero=True)
        cases = (
            (("elapsed_seconds",), 0.1),
            (("status",), "decision"),
            (("search_performed",), True),
            (("work", "transitions"), 1),
            (("work", "unused_transitions"), 1),
            (("work", "stop_reasons"), []),
            (("legal_actions", 1, "status"), "sampled"),
            (("legal_actions", 1, "mean_shaped_reward"), 0),
            (("recommendation",),
             {"card_idx": None, "target_idx": None, "label": "Pass"}),
        )
        for path, replacement in cases:
            with self.subTest(path=path):
                self.value = copy.deepcopy(baseline)
                replace_leaf(self.value, path, replacement)
                self.save()
                status, out, _ = self.cli(str(self.saved), "--decision-report")
                self.assertEqual((status, out), (2, b""))
        self.value = copy.deepcopy(baseline)
        self.value["elapsed_seconds"] = 0
        self.save()
        output = inspection.decision_inspection_html(self.saved)
        self.assertIs(type(report_fragments(output)["elapsed_seconds"]), int)

    def test_parser_caps_and_explicit_mode_never_fall_back(self):
        for raw in (
            b'{"format":1,"format":2}', b'{"a":1,"\\u0061":2}', b"\xff", b"{",
            b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1e309}',
            b'[' * 17 + b'0' + b']' * 17,
        ):
            with self.subTest(raw=raw):
                self.saved.write_bytes(raw)
                status, out, _ = self.cli(str(self.saved), "--decision-report")
                self.assertEqual((status, out), (2, b""))
        self.value["value_semantics"] = "x" * 2049
        self.save()
        status, out, _ = self.cli(str(self.saved), "--decision-report")
        self.assertEqual((status, out), (2, b""))
        self.value = synthetic_decision_report()
        self.value["selected_state"]["player"]["dots"][0]["tick"] = 10**301
        self.save()
        status, out, _ = self.cli(str(self.saved), "--decision-report")
        self.assertEqual((status, out), (2, b""))
        self.value = synthetic_decision_report()
        self.save()
        status, out, _ = self.cli(str(self.saved))
        self.assertEqual((status, out), (2, b""))
        self.value = synthetic_record()
        self.save()
        status, out, _ = self.cli(str(self.saved), "--decision-report")
        self.assertEqual((status, out), (2, b""))
        with patch.object(records, "RECORD_BYTES", 8), \
                patch.object(records, "_parse", forbidden):
            status, out, err = self.cli(str(self.saved), "--decision-report")
        self.assertEqual((status, out), (2, b""))
        self.assertIn("exceeds 8 bytes", err)

    def test_inclusive_output_limit_and_invalid_appearance_refuse_before_stdout(self):
        output = inspection.decision_inspection_html(self.saved)
        with patch.object(inspection, "HTML_BYTES", len(output)):
            self.assertEqual(inspection.decision_inspection_html(self.saved), output)
        with patch.object(inspection, "HTML_BYTES", len(output) - 1):
            status, out, err = self.cli(str(self.saved), "--decision-report")
        self.assertEqual((status, out), (1, b""))
        self.assertIn("including final LF", err)
        with patch.object(records, "_read", forbidden):
            with self.assertRaises(records.EpisodeInputError):
                inspection.decision_inspection_html(self.saved, appearance="auto")
            status, out, _ = self.cli(str(self.saved), "--decision-report",
                                      "--appearance", "auto")
        self.assertEqual((status, out), (2, b""))

    def test_selected_mode_runtime_interrupt_short_write_and_flush_failures(self):
        for failure, status in ((MemoryError("fixture resource refusal"), 1),
                                (KeyboardInterrupt(), 130)):
            with self.subTest(status=status), patch.object(
                    inspect_episode, "decision_inspection_html", side_effect=failure):
                actual, out, err = self.cli(str(self.saved), "--decision-report")
            self.assertEqual((actual, out), (status, b""))
            self.assertIn("episode inspection:", err)
        class Sink:
            def __init__(self, short):
                self.buffer = self
                self.short = short

            def write(self, data):
                return len(data) - 1 if self.short else len(data)

            def flush(self):
                if self.short:
                    raise AssertionError("short writes must not reach flush")
                raise OSError("fixture report flush refusal")

            def close(self):
                raise AssertionError("programmatic main must not close caller stdout")

        for short in (True, False):
            err = io.StringIO()
            with self.subTest(short=short), contextlib.redirect_stdout(Sink(short)), \
                    contextlib.redirect_stderr(err):
                status = inspect_episode.main([str(self.saved), "--decision-report"])
            self.assertEqual(status, 1)
            self.assertIn("incomplete document" if short else "report flush refusal",
                          err.getvalue())

    def test_help_is_usage_success_without_input_read_or_html(self):
        with patch.object(records, "_read", forbidden):
            status, out, err = self.cli("--help")
        self.assertEqual(status, 0)
        self.assertIn(b"--decision-report", out)
        self.assertNotIn(b"<!doctype html>", out)
        self.assertEqual(err, "")

    def test_actual_report_command_binary_lf_and_no_work_without_sidecar(self):
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for zero, appearance in ((False, "obscur"), (True, "clair")):
            with self.subTest(zero=zero):
                self.value = synthetic_decision_report(zero=zero)
                self.save()
                result = subprocess.run(
                    [sys.executable, "-B", str(ROOT / "inspect_episode.py"),
                     str(self.saved), "--decision-report", "--appearance", appearance],
                    cwd=self.directory, env=environment, stdin=subprocess.DEVNULL,
                    capture_output=True, timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, b"")
                self.assertTrue(result.stdout.endswith(b"</html>\n"))
                self.assertNotIn(b"\r\n", result.stdout)
                self.assertEqual(records.canonical(report_fragments(result.stdout)),
                                 records.canonical(self.value))

    def test_actual_report_flush_failure_preserves_exit_one_at_shutdown(self):
        entry = ROOT / "inspect_episode.py"
        wrapper = f'''
import io
import runpy
import sys

class RefusedFlush(io.BufferedWriter):
    def flush(self):
        raise OSError("fixture decision stdout flush refusal")

sys.path.insert(0, {str(ROOT)!r})
raw = io.FileIO(sys.stdout.fileno(), "wb", closefd=False)
sys.stdout = io.TextIOWrapper(RefusedFlush(raw), encoding="utf-8")
sys.argv = [{str(entry)!r}, {str(self.saved)!r}, "--decision-report"]
runpy.run_path({str(entry)!r}, run_name="__main__")
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        result = subprocess.run(
            [sys.executable, "-B", "-c", wrapper], cwd=self.directory,
            env=environment, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(b"fixture decision stdout flush refusal", result.stderr)
        self.assertNotIn(b"Exception ignored", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)




class PairArtifact(Artifact):
    def __init__(self, data):
        self.comparisons = {}
        self.alignment = None
        self.indexed = []
        self.separate = []
        super().__init__(data)

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attributes = dict(attrs)
        if "data-comparison-field" in attributes:
            field = attributes["data-comparison-field"]
            if field in self.comparisons:
                raise AssertionError("duplicate comparison branch")
            self.comparisons[field] = (
                attributes["data-comparison-status"],
                attributes["data-first-difference"],
            )
        if "data-choice-alignment" in attributes:
            self.alignment = attributes["data-choice-alignment"]
        if "data-indexed-comparison" in attributes:
            self.indexed.append(attributes["data-indexed-comparison"])
        if "data-separate-alternative" in attributes:
            self.separate.append(attributes["data-separate-alternative"])


class DecisionComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-pair-inspection-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.left_path = self.directory / "caller-left-private.json"
        self.right_path = self.directory / "caller-right-private.json"
        self.left = synthetic_decision_report()
        self.right = copy.deepcopy(self.left)
        self.save()

    cli = InspectionTests.cli

    def save(self):
        for path, value in ((self.left_path, self.left), (self.right_path, self.right)):
            path.write_bytes(json.dumps(value, ensure_ascii=True, indent=1,
                                        allow_nan=False).encode("utf-8"))

    def pair_cli(self, *arguments):
        return self.cli(str(self.left_path), "--decision-report", "--compare-report",
                        str(self.right_path), *arguments)

    def typed(self, expected, actual):
        self.assertIs(type(actual), type(expected))
        if isinstance(expected, dict):
            self.assertEqual(set(actual), set(expected))
            for name in expected:
                self.typed(expected[name], actual[name])
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for left, right in zip(expected, actual, strict=True):
                self.typed(left, right)
        elif isinstance(expected, float):
            self.assertEqual(actual.hex(), expected.hex())
        else:
            self.assertEqual(actual, expected)

    def test_complete_pair_fragments_in_both_editions_preserve_types_and_inputs(self):
        self.right = synthetic_decision_report(zero=True)
        self.save()
        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (self.left_path, self.right_path)
        }
        for appearance in ("obscur", "clair"):
            with self.subTest(appearance=appearance):
                output = inspection.decision_comparison_html(
                    self.left_path, self.right_path, appearance=appearance)
                artifact = PairArtifact(output)
                self.assertEqual(set(artifact.fragments), {
                    f"/{side}/{name}" for side in ("left", "right")
                    for name in inspection.DECISION_FIELDS
                })
                self.assertEqual(len(artifact.order), 36)
                for side, value in (("left", self.left), ("right", self.right)):
                    self.typed(value, {
                        name: artifact.fragments[f"/{side}/{name}"]
                        for name in inspection.DECISION_FIELDS
                    })
                self.assertIn(str(10**60 + 7).encode(), output)
                self.assertIn(b"-0.0", output)
                self.assertIn(b"Unvisited: no sampled mean", output)
                self.assertEqual(artifact.alignment, "available")
                for path, (raw, _) in before.items():
                    self.assertIn(hashlib.sha256(raw).hexdigest().encode(), output)
                    self.assertNotIn(path.name.encode(), output)
                self.assertNotIn(str(self.directory).encode(), output)
                self.assertTrue(output.endswith(b"</html>\n"))
                self.assertNotIn(b"\r\n", output)
        for path, (raw, mtime) in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (raw, mtime))

    def test_same_report_has_eighteen_typed_branch_decisions_in_grouped_order(self):
        artifact = PairArtifact(inspection.decision_comparison_html(
            self.left_path, self.right_path))
        expected = [
            "format", "schema_version", "status", "search_performed", "source_record",
            "selection", "selected_state", "configuration", "value_semantics",
            "stored_action", "stored_provenance", "implementation",
            "identity_comparisons", "work", "elapsed_seconds", "legal_actions",
            "ranking", "recommendation",
        ]
        self.assertEqual(list(artifact.comparisons), expected)
        self.assertEqual(list(artifact.comparisons.values()), [("same", "")] * 18)
        self.assertEqual(artifact.alignment, "available")
        self.assertEqual(len(artifact.indexed), len(self.left["legal_actions"]))
        self.assertFalse(artifact.separate)

    def test_capture_parse_validation_and_differences_have_no_work(self):
        denied = (
            "load_content", "load_snapshot", "observed_identity",
            "implementation_identity", "_record_owner", "record_episode",
            "replay_episode", "play_game", "is_legal_action", "legal_actions",
            "normalized", "rng_digest",
        )
        captured = [self.left_path.read_bytes(), self.right_path.read_bytes()]
        with contextlib.ExitStack() as stack:
            for name in denied:
                stack.enter_context(patch.object(records, name, forbidden))
            for name in ("Action", "Card", "Combatant", "GameState", "Charm", "DoT"):
                stack.enter_context(patch.object(getattr(records, name), "__init__",
                                                forbidden))
            stack.enter_context(patch.object(records.random, "Random", forbidden))
            stack.enter_context(patch.dict(
                sys.modules, {"game.episode_decision": None}))
            read = stack.enter_context(patch.object(records, "_read",
                                                    wraps=records._read))
            parse = stack.enter_context(patch.object(records, "_parse",
                                                     wraps=records._parse))
            validate = stack.enter_context(patch.object(
                inspection, "validate_decision_report",
                wraps=inspection.validate_decision_report))
            difference = stack.enter_context(patch.object(
                records, "first_difference", wraps=records.first_difference))
            output = inspection.decision_comparison_html(
                self.left_path, self.right_path)
        self.assertEqual([call.args for call in read.call_args_list], [
            (self.left_path, "Left decision report", records.RECORD_BYTES),
            (self.right_path, "Right decision report",
             records.RECORD_BYTES - len(captured[0])),
        ])
        self.assertEqual([call.args for call in parse.call_args_list], [
            (captured[0], "Left decision report", 200_000, 10**300),
            (captured[1], "Right decision report", 200_000, 10**300),
        ])
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(difference.call_count, 18)
        self.assertEqual([call.args[2] for call in difference.call_args_list],
                         ["/" + name for name in inspection.DECISION_FIELDS])
        self.assertEqual(len(PairArtifact(output).fragments), 36)

    def test_captured_buffers_own_identity_after_both_paths_change(self):
        original_read = records._read
        captured = {
            self.left_path: self.left_path.read_bytes(),
            self.right_path: self.right_path.read_bytes(),
        }

        def capture_then_change(path, role, limit):
            result = original_read(path, role, limit)
            path.write_bytes(b"changed after its capture")
            return result

        with patch.object(records, "_read", side_effect=capture_then_change) as read:
            output = inspection.decision_comparison_html(
                self.left_path, self.right_path)
        self.assertEqual(read.call_count, 2)
        artifact = PairArtifact(output)
        for side, path, expected in (
            ("left", self.left_path, self.left),
            ("right", self.right_path, self.right),
        ):
            self.assertIn(hashlib.sha256(captured[path]).hexdigest().encode(), output)
            self.typed(expected, {
                name: artifact.fragments[f"/{side}/{name}"]
                for name in inspection.DECISION_FIELDS
            })

    def test_same_path_is_two_independent_captures_without_a_cache(self):
        self.right["selected_state"]["player"]["hp"] = 89
        second = json.dumps(self.right, allow_nan=False).encode()
        first = self.left_path.read_bytes()
        with patch.object(records, "_read", side_effect=[first, second]) as read:
            output = inspection.decision_comparison_html(self.left_path, self.left_path)
        self.assertEqual(read.call_count, 2)
        artifact = PairArtifact(output)
        self.assertEqual(artifact.alignment, "unavailable")
        self.assertEqual(artifact.comparisons["selected_state"],
                         ("different", "/selected_state/player/hp"))
        self.assertIn(hashlib.sha256(first).hexdigest().encode(), output)
        self.assertIn(hashlib.sha256(second).hexdigest().encode(), output)

    def test_explicit_mode_and_appearance_refuse_before_any_input_read(self):
        with patch.object(records, "_read", forbidden):
            status, out, err = self.cli(str(self.left_path), "--compare-report",
                                       str(self.right_path))
            self.assertEqual((status, out), (2, b""))
            self.assertIn("--compare-report requires --decision-report", err)
            with self.assertRaisesRegex(records.EpisodeInputError, "appearance"):
                inspection.decision_comparison_html(
                    self.left_path, self.right_path, appearance="auto")
            status, out, _ = self.pair_cli("--appearance", "auto")
            self.assertEqual((status, out), (2, b""))

    def test_aggregate_bytes_are_inclusive_and_second_gets_remaining_allowance(self):
        total = len(self.left_path.read_bytes()) + len(self.right_path.read_bytes())
        with patch.object(records, "RECORD_BYTES", total):
            self.assertEqual(self.pair_cli()[0], 0)
        with patch.object(records, "RECORD_BYTES", total - 1):
            status, out, err = self.pair_cli()
        self.assertEqual((status, out), (2, b""))
        self.assertIn("Right decision report", err)
        self.assertIn("exceeds", err)
        with patch.object(records, "RECORD_BYTES", 8), \
                patch.object(records, "_parse", forbidden):
            status, out, err = self.pair_cli()
        self.assertEqual((status, out), (2, b""))
        self.assertIn("Left decision report", err)

    def test_aggregate_values_do_not_invent_a_container_level(self):
        def count(value):
            if isinstance(value, dict):
                return 1 + sum(count(item) for item in value.values())
            if isinstance(value, list):
                return 1 + sum(count(item) for item in value)
            return 1

        total = count(self.left) + count(self.right)
        with patch.object(inspection, "PAIR_VALUE_LIMIT", total):
            self.assertEqual(self.pair_cli()[0], 0)
        with patch.object(inspection, "PAIR_VALUE_LIMIT", total - 1), \
                patch.object(inspection, "_render_pair", forbidden):
            status, out, err = self.pair_cli()
        self.assertEqual((status, out), (2, b""))
        self.assertIn("aggregate values", err)
        deep = records._parse(b"[" * 16 + b"0" + b"]" * 16,
                              "literal depth witness", 200_000, 10**300)
        with patch.object(inspection, "PAIR_VALUE_LIMIT", 34):
            inspection._pair_values(deep, deep)
        with patch.object(inspection, "PAIR_VALUE_LIMIT", 33):
            with self.assertRaisesRegex(records.EpisodeInputError, "aggregate"):
                inspection._pair_values(deep, deep)
        with self.assertRaises(records.EpisodeInputError):
            records._parse(b"[" * 17 + b"0" + b"]" * 17,
                           "literal depth refusal", 200_000, 10**300)


    def test_first_paths_keep_numeric_kinds_signed_zero_and_pointer_escaping(self):
        self.right["selected_state"]["player"]["boost"]["ember"] = 0.0
        self.right["legal_actions"][0]["value_sum"] = 0.0
        self.right["legal_actions"][0]["mean_shaped_reward"] = 0.0
        self.right["implementation"]["engine_files_sha256"] = {
            "engine/a~b/c.py": "a" * 64,
        }
        self.right["identity_comparisons"]["example_files_equal"] = False
        self.save()
        artifact = PairArtifact(inspection.decision_comparison_html(
            self.left_path, self.right_path))
        self.assertEqual(artifact.comparisons["selected_state"],
                         ("different", "/selected_state/player/boost/ember"))
        self.assertEqual(
            artifact.comparisons["legal_actions"],
            ("different", "/legal_actions/0/mean_shaped_reward"),
        )
        self.assertEqual(
            artifact.comparisons["implementation"],
            ("different", "/implementation/engine_files_sha256/engine~1a~0b~1c.py"),
        )
        self.assertEqual(
            artifact.comparisons["identity_comparisons"],
            ("different", "/identity_comparisons/example_files_equal"),
        )
        self.assertEqual(
            artifact.fragments["/left/legal_actions"][0]["value_sum"].hex(),
            "-0x0.0p+0",
        )
        self.assertEqual(
            artifact.fragments["/right/legal_actions"][0]["value_sum"].hex(),
            "0x0.0p+0",
        )

    def test_each_alignment_condition_has_an_admitted_separate_list_witness(self):
        changed_state = copy.deepcopy(self.left)
        changed_state["selected_state"]["player"]["hp"] = 89
        changed_semantics = copy.deepcopy(self.left)
        changed_semantics["value_semantics"] = "Different saved reward meaning."
        changed_horizon = copy.deepcopy(self.left)
        changed_horizon["configuration"]["horizon_rounds"] = 3
        changed_horizon["configuration"]["max_transitions"] = 12
        changed_horizon["work"]["unused_transitions"] = 4
        changed_horizon["work"]["stop_reasons"] = ["simulation_cap"]
        for value, condition in (
            (changed_state, "/selected_state"),
            (changed_semantics, "/value_semantics"),
            (changed_horizon, "/configuration/horizon_rounds"),
        ):
            with self.subTest(condition=condition):
                self.right = value
                self.save()
                output = inspection.decision_comparison_html(
                    self.left_path, self.right_path)
                artifact = PairArtifact(output)
                self.assertEqual(artifact.alignment, "unavailable")
                self.assertFalse(artifact.indexed)
                self.assertEqual(len(artifact.separate), 16)
                self.assertIn(condition.encode(), output)
                self.assertEqual(artifact.fragments["/right/configuration"],
                                 value["configuration"])
        self.assertEqual(artifact.comparisons["configuration"],
                         ("different", "/configuration/horizon_rounds"))

    def test_aligned_union_keeps_absent_unvisited_labels_and_unresolved_slots(self):
        self.right["configuration"]["seed"] = 20
        del self.right["legal_actions"][1]
        self.right["legal_actions"].append({
            "card_idx": 6, "target_idx": 7, "label": "Right unresolved slot",
            "status": "unvisited", "visits": 0, "value_sum": 0,
            "mean_shaped_reward": None,
        })
        self.right["legal_actions"][0]["label"] = "Right literal Pass"
        self.save()
        output = inspection.decision_comparison_html(self.left_path, self.right_path)
        artifact = PairArtifact(output)
        self.assertEqual(artifact.alignment, "available")
        self.assertEqual(len(artifact.indexed), 9)
        self.assertFalse(artifact.separate)
        self.assertEqual(output.count(b"Absent from this report."), 2)
        self.assertIn(b"Right literal Pass", output)
        self.assertIn(b"Literal Pass label", output)
        self.assertIn(b"Unvisited: no sampled mean", output)
        self.assertIn(b"unresolved", output)
        self.assertIn(b"Retained dead slot", output)
        self.assertEqual(artifact.fragments["/left/ranking"], self.left["ranking"])
        self.assertEqual(artifact.fragments["/right/ranking"], self.right["ranking"])
        self.assertEqual(artifact.comparisons["configuration"],
                         ("different", "/configuration/seed"))

    def test_second_input_refusals_are_contextual_without_html_or_fallback(self):
        malformed = (
            b'{"format":1,"format":2}', b"\xff", b"{", b'{"x":NaN}',
            b'{"x":1e309}', json.dumps(synthetic_record()).encode(),
        )
        for raw in malformed:
            with self.subTest(raw=raw), patch.object(
                    records, "first_difference", forbidden):
                self.right_path.write_bytes(raw)
                status, out, err = self.pair_cli()
            self.assertEqual((status, out), (2, b""))
            self.assertIn("Right decision report", err)
            self.assertNotIn("Traceback", err)
        self.right = copy.deepcopy(self.left)
        self.right["configuration"]["horizon"] = 2
        self.save()
        status, out, err = self.pair_cli()
        self.assertEqual((status, out), (2, b""))
        self.assertIn("Right decision report", err)
        self.assertIn("/configuration", err)
        self.left_path.write_bytes(b"{")
        with patch.object(inspection, "_render_pair", forbidden), \
                patch.object(records, "_read", wraps=records._read) as read:
            status, out, err = self.pair_cli()
        self.assertEqual((status, out), (2, b""))
        self.assertIn("Left decision report", err)
        self.assertEqual(read.call_count, 1)

    def test_hostile_saved_strings_remain_text_and_navigation_is_local(self):
        hostile = '<img src="https://example.invalid/a" onerror="alert(1)">\x00'
        self.right["value_semantics"] = hostile
        self.right["selected_state"]["hand"][0]["name"] = hostile[:128]
        self.save()
        output = inspection.decision_comparison_html(self.left_path, self.right_path)
        artifact = PairArtifact(output)
        self.assertNotIn("img", artifact.tags)
        self.assertNotIn("script", artifact.tags)
        self.assertTrue(all(link.startswith("#") and link[1:] in artifact.ids
                            for link in artifact.links))
        self.assertEqual(len(artifact.ids), len(set(artifact.ids)))
        self.assertFalse(any(name.startswith("on") or name in ("src", "srcdoc")
                             for name, _ in artifact.attributes))
        self.assertIn(b"\\u0000", output)
        self.assertNotIn(b"url(", output)
        self.assertIn(b"font-synthesis:none", output)
        self.assertEqual(artifact.fragments["/right/value_semantics"], hostile)
        self.assertIn(b"not origin authentication", output)
        self.assertIn(b"not a simultaneous snapshot", output)

    def test_complete_output_bound_and_comparison_error_fail_before_stdout(self):
        output = inspection.decision_comparison_html(self.left_path, self.right_path)
        with patch.object(inspection, "HTML_BYTES", len(output)):
            self.assertEqual(inspection.decision_comparison_html(
                self.left_path, self.right_path), output)
        with patch.object(inspection, "HTML_BYTES", len(output) - 1):
            status, out, err = self.pair_cli()
        self.assertEqual((status, out), (1, b""))
        self.assertIn("including final LF", err)
        with patch.object(records, "first_difference",
                          side_effect=records.EpisodeRuntimeError("fixture traversal")):
            status, out, err = self.pair_cli()
        self.assertEqual((status, out), (1, b""))
        self.assertIn("admitted decision comparison cannot be compared", err)
        self.assertIn("fixture traversal", err)
        self.assertNotIn("Traceback", err)

    def test_pair_dispatch_retains_old_modes_and_sink_failure_phases(self):
        for arguments, function in (
            ([str(self.left_path)], "inspection_html"),
            ([str(self.left_path), "--decision-report"], "decision_inspection_html"),
        ):
            with self.subTest(function=function), patch.object(
                    inspect_episode, function,
                    return_value=b"literal old route\n") as old:
                status, out, err = self.cli(*arguments)
            self.assertEqual((status, out, err), (0, b"literal old route\n", ""))
            old.assert_called_once_with(self.left_path, appearance="obscur")

        class Sink:
            def __init__(self, short):
                self.buffer = self
                self.short = short

            def write(self, data):
                return len(data) - 1 if self.short else len(data)

            def flush(self):
                if self.short:
                    raise AssertionError("short writes must not reach flush")
                raise OSError("fixture paired flush refusal")

            def close(self):
                raise AssertionError("programmatic main must retain caller stdout")

        for short in (True, False):
            err = io.StringIO()
            with self.subTest(short=short), contextlib.redirect_stdout(Sink(short)), \
                    contextlib.redirect_stderr(err):
                status = inspect_episode.main([
                    str(self.left_path), "--decision-report", "--compare-report",
                    str(self.right_path),
                ])
            self.assertEqual(status, 1)
            self.assertIn("incomplete document" if short else "paired flush refusal",
                          err.getvalue())
        for failure, expected in ((MemoryError("fixture pair resource"), 1),
                                  (KeyboardInterrupt(), 130)):
            with self.subTest(status=expected), patch.object(
                    inspect_episode, "decision_comparison_html", side_effect=failure):
                status, out, err = self.pair_cli()
            self.assertEqual((status, out), (expected, b""))
            self.assertIn("episode inspection:", err)

    def test_actual_paired_flush_failure_retires_failed_buffer_at_shutdown(self):
        self.right = synthetic_decision_report(zero=True)
        self.save()
        entry = ROOT / "inspect_episode.py"
        program = f"""
import io
import runpy
import sys
import tempfile
class RefusedFlush(io.BufferedWriter):
    def flush(self):
        raise OSError("fixture paired stdout flush refusal")
stream = tempfile.TemporaryFile()
sys.stdout = io.TextIOWrapper(RefusedFlush(stream), encoding="utf-8")
sys.argv = [{str(entry)!r}, {str(self.left_path)!r}, "--decision-report",
            "--compare-report", {str(self.right_path)!r}]
runpy.run_path({str(entry)!r}, run_name="__main__")
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", program], cwd=ROOT,
            capture_output=True, timeout=10, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"fixture paired stdout flush refusal", result.stderr)
        self.assertNotIn(b"Exception ignored", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

if __name__ == "__main__":
    unittest.main()
