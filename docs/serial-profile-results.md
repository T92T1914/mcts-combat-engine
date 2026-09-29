# Serial profiling result

[Protocol](serial-profile-protocol.json) | [Raw first attempt](serial-profile-results.json) | [Reproduction](serial-profile.md)

The measured work does not justify a native port in this phase. Legal action
enumeration is the largest individual self-time function, but it represents
8.90 to 10.34 percent of recorded self time across these three decisions. The
remaining cost is spread across action hashing, search traversal, simulator
updates, random choices and Python object operations. I kept the engine
unchanged instead of expanding a small profiling task into a second simulator.

All six searches completed 3,000 simulations and 15,000 transitions. Each
instrumented run exactly matched its control's actual work, stop reasons, raw
root visit counts and value sums, rankings and final random generator state.
The input states remained unchanged. There were no retries or safety-cap
shortfalls in this attempt.

## Recorded work and time

| Initial scenario | Control seconds | Instrumented seconds | Simulations per execution | Transitions per execution | Computational match |
| --- | ---: | ---: | ---: | ---: | --- |
| Duel | 0.231919 | 0.758294 | 3,000 | 15,000 | Exact |
| Gauntlet | 0.317453 | 1.088050 | 3,000 | 15,000 | Exact |
| Boss | 0.239120 | 0.992428 | 3,000 | 15,000 | Exact |

These are single observations of three fixed initial states on a shared Windows
machine. Other engineering agents held tests and builds during collection.
Ordinary user applications remained in place, and external load and hardware
counters were not measured. This is not an exclusive-machine performance test.
Construction, serialization and file writes are outside the search timer.

cProfile changes the measured execution cost. The instrumented times are
diagnostic observations, not evidence of an optimization speedup or slowdown.
Self time excludes called functions. Cumulative time includes them, overlaps
between callers and callees, and cannot be added to obtain elapsed time.

## Where the instrumented time went

Percentages below divide a function's self time by the sum of recorded self
times in that instrumented run. They describe this profiler's observations,
not predicted fractions of uninstrumented elapsed time.

| Function | Duel percent | Gauntlet percent | Boss percent |
| --- | ---: | ---: | ---: |
| `legal_actions` | 10.34 | 8.90 | 9.89 |
| Generated action `__hash__` | 7.75 | 6.42 | 7.18 |
| `advance_round` | 6.46 | 6.96 | 6.04 |
| `Node.ucb1` | 5.32 | 4.54 | 5.08 |
| `cast` | 4.83 | 5.91 | 4.60 |
| `math.log` | 0.88 | 0.74 | 0.84 |
| `math.sqrt` | 0.67 | 0.58 | 0.64 |

The raw record retains every function, including calls and cumulative time.
For example, UCB evaluation called `math.log` 64,748 times in Duel, 78,773 in
Gauntlet and 64,711 in Boss. Reusing a parent's logarithm across its children is
a possible later Python experiment. The logarithm itself accounts for less than
one percent of recorded self time here, which does not justify claiming a
meaningful end-to-end gain without a separate paired experiment.

## Decision and its limits

An individual native UCB call would cross a language boundary many times while
operating on Python nodes. Its arithmetic is a small part of this profile, and
no boundary cost has been measured. Porting enough surrounding work to avoid
those calls would change the scope from a narrow optimization to ownership of
the tree, action representation and simulator state. The profile does not
establish that such a port would pay for its added interface and validation
cost.

I therefore made no engine change and no native or GPU speed claim. The Python
reference, legal action behavior, random draw order, fixed work allowances and
parallel controls remain intact. This conclusion is limited to the inspected
implementation and these three conditions. It does not prove Python is optimal
or rule out a future optimization backed by a broader workload and a measured
boundary.

No full games, decision quality outcomes, allocation profiler or hardware
counters were collected. This profile does not explain every deployment
bottleneck or measure peak memory. The earlier process studies and unfavorable
results remain separate and unchanged.

Measured revision: `a8e18580401601846fbd21ab27d4731d19cceef6`.
The protocol and tested runner were committed before collection. Source hashes
remained unchanged through the run. The JSON's SHA256 is
`a528960d7c14724dbb4d90b23133310b15e52bee7ffcf9a1bf2ec910bbb5df63`.
The report is a later explanation of those retained bytes.
