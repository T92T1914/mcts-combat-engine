# Complete encounter policy capture

The separate benchmark capture compares default UCT and the existing optional
sequential halving treatment across complete modeled encounters. Both policies
request 32 simulations and 32 transitions per decision at horizon one. The
recorder retains each state before action, chosen action, work receipt, final
outcome and environment RNG checkpoint. These artifacts support inspection and
environment replay through the existing episode tools.

The [retained encounter study](encounter-outcomes.md) reports the frozen inputs,
observed terminal outcomes, actual work and inconclusive primary interval.

Capture is a measurement interface. It does not supply a statistical method,
claim stronger play, or replace the retained first action study. Freeze the
replication blocks and analysis before collecting an experiment. Keep any pilot
and deciding capture in separate new directories with their own protocols.

## Protocol and execution

The bounded UTF-8 JSON protocol declares the three built-in presets in exactly
this order, a cap of 30 rounds, 32 simulations, horizon one, an external timeout per
trial, a total collection deadline, and paired seed blocks. No custom content,
deeper horizon, priors, parallel search or search limited by a clock is admitted.

This is an illustrative input shape, not a collected experiment or frozen study:

```json
{
  "format": "mcts-encounter-policy-protocol",
  "schema_version": 1,
  "scenarios": ["duel", "gauntlet", "boss"],
  "rounds": 30,
  "sims": 32,
  "horizon": 1,
  "trial_timeout_seconds": 30,
  "collection_timeout_seconds": 240,
  "seed_blocks": [
    {
      "name": "example-0",
      "environment_seed": 1001,
      "search_seed": 2001,
      "policy_order": ["uct", "sequential_halving"]
    },
    {
      "name": "example-1",
      "environment_seed": 1002,
      "search_seed": 2002,
      "policy_order": ["sequential_halving", "uct"]
    }
  ]
}
```

Each block creates six intended slots: its three presets and two policies. Slots
run in block order, then preset order, then the declared policy order. Repeated
seed draws across blocks are permitted. Distinct block names preserve their
replication identity. Within a block, the environment and search seed magnitudes
must differ. The caller's frozen sampling design determines any further seed
domains, exclusions and counterbalancing requirements. Integer seed signs alone
do not separate Python Random streams.

The optional `metadata` object retains method and provenance material without
adding execution controls. If `metadata.freeze` is present, its `implementation`
and `content` values must exactly match the capture source and built-in content
before any child starts. Other metadata remains declared material for the
independent analysis.

Run the collector inside an external process owner with a verified process tree
bound, a total wall limit, memory enforcement and descendant retirement. Supply
its description or receipt locator explicitly:

```text
python benchmark.py --encounter-protocol protocol.json --encounter-output new-capture-directory --process-tree-bound "external owner receipt locator and limits"
```

The collector records that caller supplied declaration. It does not establish or
verify external ownership. A nonempty declaration is required. Retain the actual
external owner receipt independently. The source does not import a private
process owner or launch a second scheduling framework.

One hidden serial `episode.py record` child owns each trial. Its managed search
owner is fresh for that encounter and keeps a separate search RNG stream across
its decisions. Environment draws use another RNG object, and policy RNG draws
have their existing unused stream. Identical starting seeds pair the conditions,
but different actions can still lead to different stochastic paths.

The child has a hard external trial timeout. Its search remains clockless, which
is required by the existing halving candidate. Before another trial starts, the
collector checks the total deadline. A trial receives the smaller of its frozen
timeout and the remaining collection time. No further trials are admitted after
the deadline. The direct child is killed and reaped after a timeout. Failed kill
or reap stops admission and leaves later slots unattempted. The declared external
owner supplies the separate process tree guarantee.

## Recording and failure boundaries

Ordinary `episode.py record` calls retain schema 1 and their existing behavior.
Explicit `--root-allocation uct` or `--root-allocation sequential_halving` with
`--horizon 1` produces schema 2. Its configuration declares the existing sampling
and final selection treatment. Every returned step adds actual simulations,
transitions, unused transitions, stop reasons, legal action count, allocation
mode and allocation completion. UCT retains its existing mean reward then visits
selection. Halving retains its existing survivor selection and uniform fallback.
The capture does not rerank either candidate.

An explicit record publishes only after every returned decision spent its full
declared allowance, the search owner closed, source identity remained stable,
and the complete record passed strict admission. Missing or repeated work
callbacks, shortfalls, incomplete allocation diagnostics, failed close or failed
output prevent complete publication. No failure becomes Pass or a replacement
policy decision.

The parent captures stdout and stderr into owned temporary files, then retains
at most 8 MiB of stdout and 64 KiB of stderr in each trial directory. It records
the observed byte lengths and truncation flags and rejects overflowed output.
These bounded reads are not a quota on temporary file writes. Successful episode
stdout is independently bounded by its producer before publication. The caller
must account for transport storage in the external execution limits.

The new capture directory contains:

- `protocol.json`, the exact captured input bytes.
- `results.json`, the full intended inventory, source/content identities, final
  status, aggregate work, outcome categories and receipt references.
- `trials/00000/receipt.json`, one atomic attempt receipt per started trial,
  including episode identity, transport, elapsed time, work, outcome and error.
- `episode.json` within a successful trial directory, admitted complete episode
  bytes with their digest in the receipt.
- `stdout.raw`, `stderr.raw`, `timing.json`, `work.json` and `error.json` within
  each normally retained attempt directory.

The inventory is written before execution. Atomic per trial receipts are the
crash recovery boundary. The final inventory joins those receipt references and
hashes when collection ends. If the collector is interrupted before that final
join, its initial inventory can still show `not_attempted` for slots with retained
attempt receipts. Recover progress from those receipts and their episode hashes,
not from an unfinished aggregate report. No retry or overwrite is automatic.

Failures continue through the remaining intended slots when the direct child was
retired. A retirement failure or total deadline stops new admission. Any failed,
timed out or unattempted slot keeps its terminal outcome and unobserved work
unknown. A final capture is complete only when every intended slot completed and
source identity stayed stable. CLI exit zero means this capture contract passed.
An incomplete capture exits one and retains the incomplete inventory and receipts.

## Reading the evidence

A terminal win by round 30 is the primary binary endpoint available to a frozen
analysis. Terminal loss and an unfinished round-limit encounter are separate
reported categories. A round-limit encounter is a nonwin for that endpoint and
is not labeled a terminal loss. The model score stays separate from the terminal
result and is not a calibrated probability.

The capture summarizes observed terminal win counts and the range obtained by
assigning each missing outcome either zero or one. This is an accounting envelope,
not a confidence interval. All uncertainty formulas, statistical units and
decisions belong to the independently frozen method. An analysis should rebuild
outcomes and work from retained episodes and receipts, rather than trust the
produced aggregate summary.

Subprocess elapsed time includes interpreter startup, content admission, search,
environment execution, recording and owner close. Total capture time also
includes parent admission and artifact writes. Neither timer establishes equal
CPU cost. Equal decision allowances do not imply equal total encounter work when
policies finish in different numbers of rounds.

The existing inspection and replay commands accept strict schema 2 records:

```text
python inspect_episode.py episode.json > inspection.html
python episode.py replay episode.json
python decide_episode.py episode.json --step 0 --sims 32 --horizon 1
```

Inspection is passive admission and presentation of saved claims. Environment
replay rebuilds the original encounter and applies saved actions without creating
either search policy. Its existing identity and RNG checkpoint checks still
apply. A fresh decision from a saved state performs new search and does not
recompute or authenticate the original policy's search trace.

The complete companion includes this capture tool, benchmark entry and guide.
The engine wheel remains the nine-member `engine` package, without game content,
benchmark tools or evaluation artifacts. The saved-state reader kit keeps its
existing payload and scope.
