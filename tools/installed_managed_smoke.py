"""Exercise managed capture and inspection in the relocated installed journey.

Use the fresh journey produced by installed_companion_smoke.py. The caller owns
this acceptance process; managed capture supplies its own public workload owner.
No PR59 deciding encounter is rerun or added to its scientific evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path

import engine


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identities(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def main():
    require(os.name == "nt", "strict Windows acceptance only")
    root = Path(sys.argv[1]).resolve()
    companion = root / "relocated-companion"
    require(companion.is_dir(), "run installed_companion_smoke first")
    origin = Path(engine.__file__).resolve()
    require(origin.is_relative_to(Path(sysconfig.get_path("purelib")).resolve()),
            "engine is not installed outside the checkout")
    output = root / "managed-acceptance"
    output.mkdir(exist_ok=False)
    protocol = {
        "schema_version": 1, "scenarios": ["duel", "gauntlet", "boss"],
        "rounds": 30, "sims": 32, "horizon": 1, "trial_timeout_seconds": 5,
        "collection_timeout_seconds": 45,
        "seed_blocks": [{"name": "installed-operational-acceptance",
                         "environment_seed": 1001, "search_seed": 2001,
                         "policy_order": ["uct", "sequential_halving"]}],
        "metadata": {"purpose": "operational acceptance, excluded from PR59 study"},
    }
    protocol_path = output / "protocol.json"
    protocol_path.write_text(json.dumps(protocol) + "\n", encoding="utf-8")
    before_input = protocol_path.read_bytes()
    before_companion = identities(companion)
    calls = []

    def call(entry, arguments, expected=0, *, guard=False):
        isolated = ["-I"] if entry in {"managed_encounters.py",
                                      "recover_encounters.py"} else ["-E", "-s"]
        command = [sys.executable, *isolated, "-B", str(companion / entry), *arguments]
        if guard:
            script = (
                "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
                "import engine,subprocess;import game.episode_record as records;"
                "\n"
                "def refuse(*args,**kwargs):\n"
                " raise RuntimeError('EXECUTION REACHED DURING RECOVERY')\n"
                "engine.MCTS.__init__=refuse;engine.mcts_decider=refuse;"
                "records._record_owner=refuse;subprocess.Popen=refuse;"
                "sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')"
            )
            command = [sys.executable, "-I", "-B", "-c", script, str(companion),
                       str(companion / entry), *arguments]
        result = subprocess.run(
            command, cwd=root / "unrelated-working-directory", stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=50,
            creationflags=subprocess.CREATE_NO_WINDOW)
        name = "consumer-" + str(len(calls))
        (output / (name + ".stdout")).write_bytes(result.stdout)
        (output / (name + ".stderr")).write_bytes(result.stderr)
        calls.append({"entry": entry, "returncode": result.returncode,
                      "stdout_bytes": len(result.stdout),
                      "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                      "retained_prefix": name, "execution_guarded": guard})
        require(result.returncode == expected,
                str(calls[-1]) + ": " + result.stderr.decode("utf-8", "replace"))

    complete = output / "complete"
    call("managed_encounters.py", [str(protocol_path), str(complete),
                                    "--wall-seconds", "45"])
    owner_result = json.loads((complete / "managed-result.json").read_bytes())
    require(owner_result["status"] == "complete", "capture incomplete")
    require(owner_result["owner"]["cleanup"]["retired"], "unresolved cleanup")
    require(owner_result["owner"]["failure_kind"] is None, "owner fault hidden")
    require(not owner_result["owner"]["memory_observation"]["exceeds_requested_limit"],
            "unqualified memory observation")
    saved = identities(complete)
    recovered = output / "complete-recovery.json"
    call("recover_encounters.py", [str(complete / "capture"), "--output",
                                    str(recovered)], guard=True)
    report = json.loads(recovered.read_bytes())
    require(report["summary"]["intended_trials"] == 6 and
            report["summary"]["classifications"]["complete_admitted"] == 6 and
            report["inventory_evidence_consistent"], "complete evidence not admitted")
    require(identities(complete) == saved, "recovery changed retained evidence")
    total_simulations = total_transitions = 0
    slots = [(scenario, policy) for scenario in ("duel", "gauntlet", "boss")
             for policy in ("uct", "sequential_halving")]
    for index, (scenario, policy) in enumerate(slots):
        path = complete / "capture/trials" / f"{index:05d}" / "episode.json"
        record = json.loads(path.read_bytes())
        require(record["implementation"]["engine_import_kind"] == "site-packages",
                "managed recorder did not use installed engine")
        require(record["scenario"]["name"] == scenario and
                record["scenario"]["environment_seed"] == 1001 and
                record["configuration"]["root_allocation"] == policy and
                record["configuration"]["search_seed"] == 2001,
                "saved bytes disagree with independently declared slot")
        for step in record["steps"]:
            work = step["work"]
            require(work["simulations"] == 32 and work["transitions"] == 32 and
                    work["unused_transitions"] == 0 and work["max_transitions"] == 32,
                    "saved decision did not complete declared 32/32 work")
            total_simulations += work["simulations"]
            total_transitions += work["transitions"]
    episode = complete / "capture/trials/00000/episode.json"
    call("episode.py", ["replay", str(episode)])
    call("inspect_episode.py", [str(episode), "--appearance", "obscur"])
    call("decide_episode.py", [str(episode), "--step", "0", "--seed", "19",
                               "--sims", "2", "--horizon", "1"])

    cancelled = output / "cancelled"
    cancellation = cancelled / "cancel.request"
    observed_intent = []

    def request_cancellation():
        until = time.monotonic() + 5
        intent = cancelled / "capture/trials/00001/admission-intent.json"
        while time.monotonic() < until:
            if intent.exists():
                cancellation.touch()
                observed_intent.append(True)
                return
            time.sleep(0.002)

    requester = threading.Thread(target=request_cancellation)
    requester.start()
    try:
        call("managed_encounters.py", [str(protocol_path), str(cancelled),
                                        "--wall-seconds", "45"], 130)
    finally:
        requester.join(timeout=6)
    require(observed_intent and not requester.is_alive(), "no admitted cancellation")
    cancelled_result = json.loads((cancelled / "managed-result.json").read_bytes())
    require(cancelled_result["status"] == "incomplete" and
            cancelled_result["owner"]["failure_kind"] == "cancelled" and
            cancelled_result["owner"]["cleanup"]["retired"],
            "cancellation or retirement misreported")
    saved_cancelled = identities(cancelled)
    cancelled_recovery = output / "cancelled-recovery.json"
    call("recover_encounters.py", [str(cancelled / "capture"), "--output",
                                    str(cancelled_recovery)], guard=True)
    stopped = json.loads(cancelled_recovery.read_bytes())
    require(stopped["summary"]["intended_trials"] == 6 and
            1 <= stopped["summary"]["classifications"]["complete_admitted"] < 6,
            "cancellation replaced or lost the intended inventory")
    require(identities(cancelled) == saved_cancelled, "stopped evidence changed")

    timed = output / "timeout"
    call("managed_encounters.py", [str(protocol_path), str(timed),
                                    "--wall-seconds", "0.1"], 1)
    timed_result = json.loads((timed / "managed-result.json").read_bytes())
    require(timed_result["status"] == "incomplete" and
            timed_result["owner"]["failure_kind"] == "timeout" and
            timed_result["owner"]["cleanup"]["retired"], "timeout misreported")
    following = output / "following"
    call("managed_encounters.py", [str(protocol_path), str(following),
                                    "--wall-seconds", "45"])
    require(json.loads((following / "managed-result.json").read_bytes())["status"] ==
            "complete", "fresh capture after failure did not complete")
    require(protocol_path.read_bytes() == before_input, "input changed")
    require(identities(companion) == before_companion, "companion source changed")
    summary = {"installed_engine": str(origin), "relocated_companion": str(companion),
               "saved_simulations": total_simulations,
               "saved_transitions": total_transitions,
               "complete_recovery": report["summary"],
               "cancelled_recovery": stopped["summary"],
               "calls": calls, "originals_unchanged": True,
               "scientific_data_added": False}
    (output / "acceptance.json").write_text(json.dumps(summary, indent=2) + "\n",
                                            encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
