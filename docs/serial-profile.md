# Serial search profiling

The [declared protocol](serial-profile-protocol.json) isolates the cost of three
fixed serial decisions before choosing an optimization. It retains the existing
Python implementation, action rules and search randomness. This investigation
does not repeat the process studies or overwrite their results.

Run the committed diagnostic from a clean checkout:

```sh
python tools/run_serial_profile.py --output serial-profile.json --conditions "Describe the observed shared machine conditions"
```

Use a new output path outside the checkout. The runner refuses to replace an
attempt. It runs one control and one instrumented search for each of Duel,
Gauntlet and Boss, with 3,000 simulations and a 15,000 transition ceiling.
Construction and result writing remain outside the search timer. A 60 second
safety cap is checked between simulations. A shortfall stops collection and
remains in the receipt.

Each pair must preserve actual work, action rankings, raw root statistics,
the final random generator state and the original input. cProfile records
function call counts, self time and cumulative time. Its instrumentation adds
cost, so the instrumented time is not an optimization result. Cumulative times
include nested calls and cannot be added as if they were disjoint work.

The [first result](serial-profile-results.md) supports keeping the engine
unchanged for this bounded investigation. The raw function costs and decision
are retained. Any later change must preserve move legality, fixed allowances,
random draws and arithmetic order. No native port is assumed. A documented
decision to keep the current implementation is a valid outcome when the
measured cost does not justify a change.

This protocol was prepared and committed before collecting its results.
Measurement is a separate step, with no competing agent benchmark or build on
the same machine.
Ordinary user applications stay in place. These controls do not turn a shared
development computer into a dedicated benchmark host.

Check the retained first attempt without executing another search:

```sh
python tools/validate_serial_profile.py
```

The validator checks the retained bytes, declared conditions, actual work,
unchanged roots, matching random state and independently reconstructed rankings.
It also checks profiler values and sanitized paths. It does not replace native
execution evidence or demonstrate an optimization.
