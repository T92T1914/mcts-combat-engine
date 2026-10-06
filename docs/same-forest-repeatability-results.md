# Repeated same-forest execution

[Public receipt derivative](same-forest-repeatability-public-receipts.json) | [Predeclared protocol](same-forest-repeatability-protocol.json) | [Original one-observation control](same-forest-results.md)

All 216 executions completed and matched the same computational receipts within every condition across six fresh Python controller processes. Each controller ran two repetitions per condition. Each execution retained 12,000 simulations and 60,000 transitions. The search algorithm and seeds did not change.

The table estimates a geometric mean of paired sequential/process wall-time ratios. Above 1 favors processes. Each approximate 95-percent interval uses six process-block means, df 5 and the predeclared rounded Student-t critical value 2.571. The two inner repetitions are not counted as independent processes. These are individual intervals, not simultaneous confidence across all 24 comparisons.

| Scenario | Roots | Timer | Process | Ratio | Approximate 95% interval | Decision |
| --- | ---: | --- | --- | ---: | --- | --- |
| duel | 2 | elapsed_s | cold | 1.598 | 1.453 to 1.758 | bounded advantage |
| duel | 2 | elapsed_s | warm | 2.095 | 1.854 to 2.369 | bounded advantage |
| duel | 2 | complete_call_s | cold | 1.591 | 1.446 to 1.750 | bounded advantage |
| duel | 2 | complete_call_s | warm | 1.589 | 1.408 to 1.794 | bounded advantage |
| duel | 4 | elapsed_s | cold | 2.350 | 2.074 to 2.663 | bounded advantage |
| duel | 4 | elapsed_s | warm | 3.792 | 3.256 to 4.415 | bounded advantage |
| duel | 4 | complete_call_s | cold | 2.332 | 2.059 to 2.642 | bounded advantage |
| duel | 4 | complete_call_s | warm | 2.254 | 1.972 to 2.577 | bounded advantage |
| gauntlet | 2 | elapsed_s | cold | 1.707 | 1.547 to 1.884 | bounded advantage |
| gauntlet | 2 | elapsed_s | warm | 2.145 | 1.732 to 2.657 | bounded advantage |
| gauntlet | 2 | complete_call_s | cold | 1.701 | 1.542 to 1.878 | bounded advantage |
| gauntlet | 2 | complete_call_s | warm | 1.762 | 1.427 to 2.174 | bounded advantage |
| gauntlet | 4 | elapsed_s | cold | 2.479 | 2.274 to 2.703 | bounded advantage |
| gauntlet | 4 | elapsed_s | warm | 3.601 | 3.139 to 4.130 | bounded advantage |
| gauntlet | 4 | complete_call_s | cold | 2.464 | 2.260 to 2.686 | bounded advantage |
| gauntlet | 4 | complete_call_s | warm | 2.418 | 2.144 to 2.729 | bounded advantage |
| boss | 2 | elapsed_s | cold | 1.671 | 1.468 to 1.902 | bounded advantage |
| boss | 2 | elapsed_s | warm | 2.090 | 1.914 to 2.282 | bounded advantage |
| boss | 2 | complete_call_s | cold | 1.664 | 1.462 to 1.894 | bounded advantage |
| boss | 2 | complete_call_s | warm | 1.621 | 1.482 to 1.773 | bounded advantage |
| boss | 4 | elapsed_s | cold | 2.275 | 2.075 to 2.495 | bounded advantage |
| boss | 4 | elapsed_s | warm | 3.719 | 3.348 to 4.131 | bounded advantage |
| boss | 4 | complete_call_s | cold | 2.254 | 2.052 to 2.476 | bounded advantage |
| boss | 4 | complete_call_s | warm | 2.233 | 1.975 to 2.524 | bounded advantage |

## Timing and sampling limits

The original search timer includes engine construction in sequential and cold calls but excludes warm pool preparation. The new complete call includes preparation, the search, receipt conversion, the root-mutation check and owned pool cleanup. Controller invocation cost is retained separately and is not apportioned among modes. Overlapping components must not be added.

Fresh controllers share one machine and one interpreter installation. No rebuild or cross-machine level was sampled. The approximate interval assumes reasonably independent, approximately normal block means. Shared activity, drift and six blocks limit that assumption. Within the complete attempt, no search was discarded as warmup and no failed block was retried. There was no outcome-based early stopping or tuning. The maximum-cost rule was 300 seconds with a 70-second admission reserve.

Three fixed initial states and one seed do not represent all workloads or general search quality. Repetition cannot establish stronger play, superlinear scaling or portability. Original unfavorable observations remain in the earlier report.

Measured revision: `60bd4848427b2489e7bec4048170407b0c8f4e99`. Collection wall time: 222.922 seconds. Started: 2026-10-06T12:07:11.157429+00:00. Ended: 2026-10-06T12:10:54.042465+00:00.

Shared Windows workstation. The coordinator paused competing owned benchmarks, browser checks, compilers and renderers for this collection. Ordinary user applications and settings were unchanged. No exclusive-machine access claimed.

## Method sources and reproduction

[Kalibera and Jones, Rigorous Benchmarking in Reasonable Time](https://kar.kent.ac.uk/33611/) supplied the distinction between repetition levels through its fetched abstract, author page and repository abstract. The corrected full manuscript timed out. This supplement does not claim to implement its complete cost or Fieller model.

[NIST confidence limits for a mean](https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm) and [Student-t critical values](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3672.htm) define the declared ordinary mean interval on the process-block log ratios and the rounded df 5 value.

Validate this report without running search:

```sh
python tools/render_same_forest_repeatability.py --check
```

## Measured source snapshot

The collection used recorded local revision `60bd4848427b2489e7bec4048170407b0c8f4e99`. Its complete Git tree matches the [public measurement source snapshot](https://github.com/T92T1914/mcts-combat-engine/tree/fb7addac28a6045fcb8f6cbaedc31c4808b4058a). Both trees are `a65a176e3640c5ec8991a40231e5c550fc66a97a`, with identical paths, modes and blobs. The public commit has different commit metadata and history. This is source-tree equivalence, not preservation of the original commit identity.

No receipt revision, timer or measured value was rewritten for publication. A new collection from the public snapshot would record its public commit identity and produce a separate attempt. Use the current public checkout for the retained-data validation command above. The local analysis correction recorded below is historical. The current report generator also includes later presentation and privacy work and is not the measured source.

## Retained attempts and analysis

[Attempt provenance](same-forest-repeatability-provenance.json) | [First failed attempt derivative](same-forest-repeatability-public-failed-attempt.json)

The first collection at `600b962a69d5e46cfccdd0898a21b8e6750cd6e8` failed after one completed cell. An in-memory dataclass tuple was passed to a validator for retained JSON arrays. The saved first cell validates as JSON. This failed collection is retained and supplies no timing evidence.

After the producer correction was independently reviewed, a new whole attempt used the same frozen protocol and resource bounds. No partial block was reused and no outcome-based budget or order change was made.

The complete attempt's first analysis stopped at the nested raw-byte hash gate before producing a timing summary. All six saved blocks matched their declared hashes and the native Windows CRLF serializer. The analyzer correction accepts only exact canonical LF or CRLF forms. Changed values, arbitrary formatting and invalid stopping receipts remain rejected. Search was not rerun for this correction.

Validated analysis revision: `11e01adebd09046d7853c057f75183d4ce4b1675`. The measured source hashes were checked against committed measured-revision blobs. The current non-analyzer inputs also matched retained pins. Subsequent report and figure rendering does not change the measured revision.

Outer job wall time: 223.422 seconds. Full call wall time: 223.610 seconds. The controller observed zero active owned processes at retirement, stable input pins and a passed post-write resource gate. The retained provenance records the limits separately from the search and complete-call timers.

## Public derivative boundary

[Field-removal manifest](same-forest-repeatability-public-fields.json)

The downloads are public receipt derivatives, not the exact original raw files. They omit operating-system process IDs, the exact OS build, the Python compiler/build string and the interpreter binary hash. Python 3.11.8, Windows, spawn and 16 logical CPUs remain as resource context. Every computational receipt, timer, declared control and schedule is unchanged. Public block hashes identify derived LF records. The original private SHA256 and byte lengths are retained in provenance. Public data alone cannot verify withheld original bytes or environment fingerprints.

## Figures from the retained data

[Search interval, Clair](same-forest-repeatability-search-clair.svg) | [Search interval, Obscur](same-forest-repeatability-search-obscur.svg)

[Complete call, Clair](same-forest-repeatability-complete-clair.svg) | [Complete call, Obscur](same-forest-repeatability-complete-obscur.svg)

The points show geometric means and the horizontal bars show the individual approximate 95-percent intervals from the table. Both appearances use the same values and axis. The search timer excludes warm preparation. Complete call includes preparation and cleanup. Tables remain the selectable, nonvisual route to every plotted value.
