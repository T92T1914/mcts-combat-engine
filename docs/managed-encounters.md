# Run a managed encounter capture and inspect retained progress

The separate companion supplies `managed_encounters.py` for a small local capture
with Windows process ownership, bounded retained output and a declared artifact
allowance. `recover_encounters.py` inspects the retained capture after completion
or interruption. Neither command needs a development checkout or a private
supervisor.

Use the [companion acquisition instructions](episode-companion.md) to obtain the
complete companion and install its matching engine separately. Keep the extracted
files together when moving the companion. The engine wheel still contains only
`engine/`. The companion contains the example tools and no engine or wheel.

## Supported capture

Managed execution requires Python 3.11 or later and qualified Windows 10 or later
Job support. It admits exactly one seed block, the existing duel, gauntlet and boss
presets in that order, both existing policies, 30 rounds and 32 simulations and
transitions per decision at horizon one. Each block therefore declares six trials.
It does not add deeper sequential halving, change UCT's default or select a new
reward. This is an operational capture, not a new scientific study.

Save this as a new UTF-8 `C:\work\encounter-protocol.json`. Choose your own existing
parent directory and fresh output names.

```json
{
  "schema_version": 1,
  "scenarios": ["duel", "gauntlet", "boss"],
  "rounds": 30,
  "sims": 32,
  "horizon": 1,
  "trial_timeout_seconds": 10,
  "collection_timeout_seconds": 60,
  "seed_blocks": [
    {
      "name": "local-example",
      "environment_seed": 101,
      "search_seed": 201,
      "policy_order": ["uct", "sequential_halving"]
    }
  ]
}
```

Run with the separately installed engine environment. The output directory must
be new and outside the companion.

```powershell
$py = 'C:\work\engine-env\Scripts\python.exe'
$companion = 'C:\work\episode-companion'
& $py "$companion\managed_encounters.py" C:\work\encounter-protocol.json C:\work\encounter-run --wall-seconds 60 --cleanup-seconds 5 --memory-mib 256 --artifact-mib 32
$LASTEXITCODE
```

The caller receives status 0 only for a completed capture with successful owner
retirement and intact admitted inputs. Status 1 means refusal or incomplete
execution. Status 2 means the required platform enforcement is unavailable.
Cancellation or interruption returns 130 when the controller can finalize that
outcome. An interrupted or killed controller might produce no final response.
Inspect retained evidence before drawing any conclusion from missing output.

Ordinary [PR59 capture](https://github.com/T92T1914/mcts-combat-engine/blob/3888e6fc0d17a990f03b0eb6e2c81d00a5cd59ca/docs/encounter-policy-evaluation.md) still accepts its existing
caller supplied ownership declaration. That path remains distinct from this
explicit managed mode and keeps its previous limits.

## What the controls cover

| Control | Declared scope |
| --- | --- |
| Outer wall allowance | Collector launch and execution. Controller admission and finalization are outside this clock. Cleanup has its own allowance. |
| Cleanup allowance | Time allowed to retire owned processes, reap the worker, retire stream readers and close handles after completion, failure, cancellation or a deadline. |
| Job memory | Configured aggregate committed virtual allocation for the owned collector and recorder tree. The calling outer controller is excluded. |
| Artifact allowance | Cumulative known capture content writes, including duplicate transport and episode bytes and atomic pending writes. This is not a filesystem quota over arbitrary child writes. |
| Transport | At most 8 MiB retained stdout and 64 KiB retained stderr per trial. At most one transient 8192 byte read chunk per stream is outside the retained prefixes. Kernel pipes and interpreter buffers are separate. |

The defaults are 60 seconds of outer wall time, 5 seconds for cleanup, 256 MiB of
configured Job memory and 32 MiB of artifact writes. Admitted ranges are 0.1 to
300 seconds of wall time, 0.1 to 5 seconds of cleanup, 64 to 512 MiB of memory and
4 to 128 MiB of artifact writes. The protocol retains its separate per trial and
collection deadlines. The earliest applicable deadline starts retirement.

The controller reserves 512 KiB for bounded control files and diagnostic streams
before delegating the remaining artifact budget. The exact reservation, protocol
snapshot size and delegated allowance appear in `managed-start.json`. Every known
collector content write reserves its bytes before writing. Exhaustion prevents
that write and prevents a successful completion claim. Useful bounded prefixes
can remain even when a later receipt or aggregate cannot be written.

Memory accounting uses committed virtual allocation, not resident memory or a
promise about every historical peak. The owner records the raw observed Windows
`PeakJobMemoryUsed` value. An observed value above the configured allocation cap
refuses complete publication. The configured limit and that observation should
be read separately. They are not proof that the historical peak never exceeded a
hard numerical ceiling.

Each known worker is created hidden and suspended with Job membership established
at creation. Membership and limits are checked before its primary thread resumes.
The owner keeps its Job handle noninheritable and enables termination when its
last handle closes. A nested owner retires each recorder tree before managed
execution can admit the next trial. Unsupported Job composition or unavailable
setup refuses work. There is no fallback to a weaker process group or an
unverified caller string.

Non Windows systems refuse strict managed execution. The command does not create
cgroups, install a service, request administrator access or change system
settings. The ordinary tools and passive recovery remain separate interfaces.

## Cancellation, failure and retained artifacts

By default the cancellation request is `C:\work\encounter-run\cancel.request`.
While the run is active, create that file from another terminal:

```powershell
New-Item -Path C:\work\encounter-run\cancel.request -ItemType File
```

`--cancel-file PATH` selects a different request path. The request signals the
owner to begin retirement. File creation is not evidence that retirement has
already finished. Timeout, explicit cancellation, excessive output and other
incomplete attempts stop later managed admission. A failed retirement prevents
success and another trial.

The run directory retains:

- `protocol-input.json`, the captured original input bytes.
- `managed-start.json` and `worker-plan.json`, the admitted request and bounded
  worker plan.
- `managed-result.json`, when finalization succeeds, including owner, cleanup and
  artifact accounting.
- `capture/protocol.json` and `capture/results.json`, the existing collector
  protocol and aggregate inventory.
- `capture/trials/00000/` and subsequent intended trial directories, containing
  admission intent, bounded raw streams and available receipt, episode and
  diagnostic artifacts.

A deadline or cancellation begins cleanup. The final owner receipt distinguishes
the request from actual worker reaping, an empty Job, retired readers and closed
handles. Bounded Job member snapshots identify additional members for observation.
The owner opens process query and wait handles, checks membership in its own Job
and waits for the observed exact handles within the existing cleanup allowance.
The receipt distinguishes those handle signals from Job emptiness and direct
worker reaping. It does not prove destruction of every unobserved process object.
If the controller dies, closing its sole Job handle requests OS cleanup of the
owned members, but no final successful attestation is available. Collector failure
can leave earlier complete receipts and a current orphan intent or stream prefix.
No recovery promise covers power loss or kernel failure.

Every completed encounter uses the existing schema 2 record with explicit work and
root allocation. Ordinary schema 1 recording and the existing replay, passive
inspection and fresh decision interfaces keep their contracts. Recovery does not
rewrite old records or relax their replay identity checks.

## Inspect progress without replacing any trial

Use a stopped capture and the inner `capture` directory. Choose a new report path
outside that inner directory. The report is a separate operation and is not
charged to the original capture's artifact allowance.

```powershell
& $py "$companion\recover_encounters.py" C:\work\encounter-run\capture --output C:\work\encounter-recovery.json
```

Recovery reads bounded bytes and reconstructs the original intended inventory.
It checks receipt and episode identities, settings, source and content joins,
per decision work, diagnostic sidecars and outcomes. A separate final HP check
rejects a stored terminal result that contradicts the retained state. These
checks inspect consistency. They perform no search, environment replay, retry or
resampling.

| Classification | Meaning |
| --- | --- |
| `complete_admitted` | Retained receipt and episode claims pass the declared identity, configuration, work and outcome joins. |
| `incomplete_attempt` | An incomplete receipt, orphan admission intent or other attempt artifact is retained. No complete outcome or work is substituted. |
| `corrupt_or_contradictory` | Required evidence is malformed, missing or inconsistent with an affirmative retained claim. |
| `no_execution_evidence` | No applicable retained attempt evidence is visible. Whether work started remains unknown. |

An exact initial aggregate can be stale after completed atomic receipts appear.
Recovery admits those individual receipts rather than treating the original zero
summary as the result. Affirmative later claims still have to agree. A missing
aggregate leaves collection source and content identity unknown, so apparently
complete episode claims cannot supply their own admission authority.

Absence alone never proves a slot was never started. An admission intent proves
only that its bytes were retained, not that the worker launched or cleanup
finished. Recovery does not authenticate receipt origin or establish OS
ownership, scientific validity or statistical completeness.

The default total read allowance is 128 MiB. `--max-read-bytes` can lower that
allowance. Individual limits are 2 MiB for protocol input, 8 MiB for an episode,
4 MiB for a receipt and 64 MiB for the aggregate and generated report. Directory
entries and JSON shape are bounded. Unsafe links and reparse points, a changing
snapshot, excessive reads or an existing output file refuse the operation.
Recovery never silently skips evidence to fit a successful result.

Recovery status 0 means the inspection report was written. Read its
classifications and issues to determine which evidence was admitted. It does not
mean all trials completed. A later user selected retry would be a distinct
operation with its own immutable input and scientific implications.

## Evidence boundaries

These controls admit the known unchanged local engine and companion workload.
They do not provide a secure sandbox for malicious code, an OS filesystem quota,
a general service manager or remote execution. They do not change the accepted
[PR59 experiment or its inconclusive result](https://github.com/T92T1914/mcts-combat-engine/blob/3888e6fc0d17a990f03b0eb6e2c81d00a5cd59ca/docs/encounter-outcomes.md). Equal work
allowances per decision still do not imply equal total encounter cost.

The public implementation uses Windows Job Objects and suspended process launch.
Its ownership design draws on the public
[Solver process owner at a fixed revision](https://github.com/T92T1914/exact-blackjack-solver/tree/c5fa104375fca65404cfdf2ddda015d9eb6a54a2).
It has no runtime dependency on that repository and copies no private supervisor.
Platform definitions follow Microsoft's
[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
[process creation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)
and [Job memory limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)
documentation. Source inspection, mocked failure fixtures and actual OS checks
remain distinct evidence.
