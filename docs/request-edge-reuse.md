# Reuse stable action edges within one search

Use the existing installed engine and separate episode companion. The engine
reuses immutable physical action coordinates within each search request, while
recomputing legality and current-hand actions for every realized state. No new
flag, command, model or record format is needed.

The qualified local installed API comparison had a geometric mean of condition
median paired baseline/candidate time ratios of 1.1331546109842285. Its inverse,
0.8824921068197623, corresponds to approximately 11.75 percent lower search
time under that aggregate definition. All six condition rules and three
separate Python traced-peak rules passed. Two individual timing pairs were
slower and remain in the complete results.

These are bounded pure-Python search observations on one shared Windows host.
They do not establish stronger decisions, lower complete CLI latency, compiled
or parallel speed, or a general improvement on other machines. Defaults,
rewards, selection, physical action identity and work limits are unchanged.

## Complete the existing installed journey

Follow [the companion installation guide](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-companion.md).
Download the complete companion, verify its checksum and install the engine
from the source revision in its manifest. The wheel contains only `engine/`.
The companion separately carries the example entries, documentation and
evidence. A development checkout and development extras are unnecessary.

The examples below use the already distributed D1 custom inputs from the
[search-allowance diagnostic](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-search-allowance.md).
They create a new episode under the current producer, so they do not attempt to
rewrite or replay an older study capture with different engine hashes.

Use PowerShell 7.4 or later for byte-preserving native stdout redirection. Use
fresh output paths in an existing parent directory, keep stderr separate and
check `$LASTEXITCODE` after every command. Shell redirection can create or
overwrite a file even when the command fails. These paths follow the companion
installation guide:

```powershell
$py = 'C:\work\engine-env\Scripts\python.exe'
$companion = 'C:\work\episode-companion'
$inputs = "$companion\docs\search-allowance"
& $py "$companion\episode.py" record D1 --cards "$inputs\cards.json" --scenarios "$inputs\scenarios.json" --environment-seed 1103 --search-seed 0 --rounds 1 --sims 1 --horizon 1 > C:\work\edge-episode.json
& $py "$companion\episode.py" replay C:\work\edge-episode.json --cards "$inputs\cards.json" --scenarios "$inputs\scenarios.json" > C:\work\edge-replay.json
& $py "$companion\inspect_episode.py" C:\work\edge-episode.json --appearance obscur > C:\work\edge-episode.html
```

Replay applies the saved actions and environment random stream without search.
It requires matching source/runtime identities and the original custom content
bytes. Inspecting the episode is passive and performs no replay or search.

Request two fresh bounded decisions from the same retained pre-action state.
Each has its own explicit search seed and allowance. The existing hand is read
without refilling it or continuing the capture's search random stream:

```powershell
& $py "$companion\decide_episode.py" C:\work\edge-episode.json --step 0 --seed 19 --sims 8 --horizon 1 --exploration 1.2 --final-action-rule mean_visits > C:\work\edge-decision-a.json
& $py "$companion\decide_episode.py" C:\work\edge-episode.json --step 0 --seed 23 --sims 8 --horizon 1 --exploration 1.2 --final-action-rule mean_visits > C:\work\edge-decision-b.json
& $py "$companion\inspect_episode.py" C:\work\edge-decision-a.json --decision-report --compare-report C:\work\edge-decision-b.json --appearance obscur > C:\work\edge-decisions.html
& $py "$companion\reference_episode.py" C:\work\edge-decision-a.json --model one-round --method physical --max-paths 100 --max-total-paths 800 --max-seconds 1 > C:\work\edge-reference-a.json
& $py "$companion\reference_episode.py" C:\work\edge-decision-b.json --model one-round --method physical --max-paths 100 --max-total-paths 800 --max-seconds 1 > C:\work\edge-reference-b.json
& $py "$companion\reference_episode.py" C:\work\edge-reference-a.json --inspect --compare-report C:\work\edge-reference-b.json --appearance obscur > C:\work\edge-reference-comparison.html
```

Read the complete status and source-identity fields before using a result. A
refusal or incomplete output is not a verified decision. The HTML displays
the saved physical actions, source identities, exact reference values and ties,
selected losses and comparison eligibility. It does not run another search or
reference calculation. This small horizon-one journey exercises the supported
producer and consumer interfaces. It does not reproduce the performance study's
horizon-three and horizon-six workload.

The existing [bounded adaptive reference](https://github.com/T92T1914/mcts-combat-engine/blob/main/docs/episode-adaptive-reference.md)
also uses the same qualified source admission. Its model, domain, resource
limits and independent numerical method are unchanged.

## What is reused

An Action holds a physical card-slot index and an optional target index. During
tree selection, the edge uses the original root hand slot, while the action
applied to the simulator uses the card's current position after earlier
removals. Two slots can reference the same Card object and still represent
different physical actions.

The search-local table is keyed by original slot and target. The first
occurrence creates the frozen edge value, and later occurrences reuse that
value at any selection depth. Each realized state still produces a fresh
ordered legal-action list and a fresh mapping to current-hand actions. Pips,
living targets, depletion and newly legal options are checked every time. PASS
retains its existing behavior. The table is not stored on a Node, policy,
process pool or engine between decisions, and returned Actions do not carry a
reference to it.

The [implementation](https://github.com/T92T1914/mcts-combat-engine/blob/main/engine/mcts.py)
changes this construction path only. The other eight engine payloads, including
the Action type, simulator, rules, state arithmetic, managed policy and parallel
interfaces, are byte-identical to the measured baseline. Selection order,
random draws, reward arithmetic and declared work remain the same. Existing
caller-owned input and read-only definition responsibilities still apply.

Independent qualification compared eight complete trace pairs, covering ten
search requests per engine. It retained intermediate states, ordered
legality/root-slot mappings, expansion/UCB choices, RNG endpoints, rule events,
binary64 rewards and backpropagation, complete root statistics and lifetime
observations. The paired collection includes 1,122 transitions per engine and
905 complete backpropagation updates. It covers duplicate copies, changing
pips/targets, priors, boss rules/DoT, pass-only, terminal, zero-work,
transition-remainder and repeated-request cases. These are finite execution
checks plus the source preservation argument. They are not a proof of a new
objective's quality or a universal memory bound.

## Frozen local measurement

[protocol.json](request-edge-reuse/protocol.json) records the prospectively
declared controls and decision rules. [results.json](request-edge-reuse/results.json)
retains all thirty timing pairs, six separate memory cells, full measured and
warmup computation receipts, condition medians, adverse observations and source
identities. These are static evidence documents, not new engine input formats
or a claim that every retained private review artifact is bundled.

The timing comparison used installed baseline and candidate pure-Python wheels,
the same separate companion, CPython 3.11.8 and an AMD Ryzen 7 7800X3D on Windows.
The host was shared and not exclusively controlled. Processes ran serially
under the existing Windows owner, with a 512-MiB aggregate committed-memory
ceiling, a thirty-second outer wall per operation and bounded cleanup/transport.
Those resource limits are distinct from the measured Python traced peaks.

Each measured search used 3,000 simulations, a transition ceiling of horizon
times 3,000, a 60,000-ms search safety cap, exploration 1.2 and the existing
mean-then-visits final ranking, without priors. Ordinary scenario construction
used the declared environment seed, then player pips were set to seven. Each
process first ran a disclosed 300-simulation warmup with the same state/seed
and a separate root and engine. Five baseline/candidate pairs per condition
alternated order. There was no unreported warmup, timing resampling, failed
cell or criterion change.

| Condition | Environment / search seeds | Horizon | Median paired baseline/candidate search-time ratio |
| --- | --- | ---: | ---: |
| Duel | 302 / 44 | 3 | 1.152042404732763 |
| Duel | 778 / 903 | 6 | 1.1059543856841143 |
| Gauntlet | 302 / 44 | 3 | 1.1770673192759307 |
| Gauntlet | 778 / 903 | 6 | 1.127111207007619 |
| Boss | 302 / 44 | 3 | 1.1254676937100012 |
| Boss | 778 / 903 | 6 | 1.1128284977216887 |

The timer surrounds `MCTS.search`, including its clock checks, fresh legality,
selection, rollout, transitions, backpropagation and ranking. Imports,
state/engine preparation, warmup, process start/containment/cleanup, input
admission and receipt writing are excluded. No profiler or intermediate trace
runs inside these timed calls. This boundary measures search-only API cost.

For each condition, the metric is the median of five paired ratios. The
aggregate is their equally weighted geometric mean, with larger values
favoring the candidate. The frozen rule requires an aggregate of at least
1.05 and each inverse condition median at most 1.05. Every rule passed.
The reported 11.75-percent reduction comes from the inverse aggregate ratio,
not a ratio of pooled elapsed seconds or a promise about any one request.

Two individual pairs were adverse. Gauntlet 302 repetition four took
0.26153920000069775 baseline seconds and 0.26707680000072287 candidate seconds,
approximately 2.12 percent slower. Gauntlet 778 repetition zero took
0.43106880000050296 and 0.4311092000007193 seconds, approximately 0.00937 percent
slower. Both remain in the condition medians and complete data.

Separate warmed `tracemalloc` cells used environment seed 300, search seed 42,
horizon five and the same work limits. There was one observation per engine
per scenario. Every candidate/baseline ratio passed the frozen 1.10 maximum:

| Scenario | Baseline peak traced bytes | Candidate peak traced bytes | Candidate/baseline |
| --- | ---: | ---: | ---: |
| Duel | 840,952 | 631,100 | 0.7504590036054376 |
| Gauntlet | 849,688 | 628,624 | 0.7398292078974871 |
| Boss | 842,928 | 630,708 | 0.7482347246739935 |

These peaks cover traced Python allocations during the declared warmed search.
They do not measure resident memory, committed-memory reduction, cold start,
total allocation volume or arbitrary-input peaks. Memory-run elapsed times do
not enter the timing gate. The sixty-six cells completed 198,000 measured
simulations and 900,000 measured transitions, plus 19,800 warmup simulations and
90,000 warmup transitions. Every measured and warmup pair retains complete
matching computations and unchanged inputs. These totals describe executed
work and are not a performance acceptance quota.

## Preserve source and record meaning

The measured baseline is source `ae1b40e2b0fb2df57fbd500703ecb7b5b7b73171`.
The measured candidate is `1f573c798c27e374fc9755417f07951e78883867`, with MCTS
payload SHA-256
`2a53a16dc96dfaba6ed408a54598bfb61257fe42194d8cf828e11db68761c927`.
Release documentation and producer admission can add source files while
preserving that measured engine payload. The companion manifest identifies
the revision to acquire for its complete supported consumer layout.

The reference consumers explicitly admit this complete nine-payload map in
addition to the two historical qualified maps. Missing, extra or altered
payload declarations remain refused. No hash wildcard or dynamic admission is
introduced, and the numerical model identities and reference methods are
unchanged.

Historical reports retain their original hashes, declarations and status.
Passive inspection can read admitted historical documents without rewriting
them. Strict environment replay still requires the recorded implementation,
runtime and content. An equal algorithmic result does not make a new source
hash equal to an old producer or authenticate a saved report. Preserve both
the original files and any fresh results from the installed journey.
