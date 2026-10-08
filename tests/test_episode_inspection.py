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


if __name__ == "__main__":
    unittest.main()
