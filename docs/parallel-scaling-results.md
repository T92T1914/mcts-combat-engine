# Fixed work process scaling

[Interactive report](https://t92t1914.github.io/mcts-combat-engine/parallel-scaling.html) | [Raw results](parallel-scaling-results.json) | [Declared protocol](parallel-scaling-protocol.json) | [Work contract](parallel-fixed-work.md)

I added a fixed total work mode to make parallel search easier to compare. This first computational study ran 54 searches over three initial states. Every search completed 12,000 simulations and 60,000 simulator transitions. The 27 cold and warm pairs returned identical worker seeds, work counts, raw root statistics and rankings. Only their timings differ.

The two and four worker runs were faster in 36 of 36 paired comparisons with one worker. This is a bounded shared machine result, not a general scaling guarantee. Each condition was measured once. Ratios above the worker count do not establish superlinear scaling because ordinary machine activity was uncontrolled. No episodes or playing strength comparison ran.

## Paired wall time ratios

Each ratio divides the one worker wall time by the matching worker count's time for the same state, seed and cold or warm condition. Values above one are faster in this observation. The median, minimum and maximum describe nine pairs over three states. These are not nine independent scenario samples, confidence intervals or a significance test.

Paired time ratios

| Pool | Workers | Median ratio | Minimum ratio | Maximum ratio | Pairs |
| --- | --- | --- | --- | --- | --- |
| cold | 2 | 1.713 | 1.389 | 2.304 | 9 |
| cold | 4 | 2.858 | 2.084 | 2.972 | 9 |
| warm | 2 | 2.090 | 1.911 | 2.839 | 9 |
| warm | 4 | 3.884 | 2.812 | 4.592 | 9 |

## What the work contract measures

The protocol uses environment seed 300, search seeds 7, 42 and 99, a five round horizon and no priors. Each initial state has seven pips and otherwise keeps its scenario defaults. Worker counts rotate between seeds. One total allowance is split across independent roots, so two workers get 6,000 simulations each and four get 3,000 each. Changing the worker count changes the trees, not just the scheduling of one tree.

Warm means a second search on the same process pool with fresh trees and the same derived seeds. It does not reuse a search tree. One worker runs locally without process startup. The multiworker cold condition includes waiting for every spawned process to announce readiness.

Gauntlet searches selected different targets across configurations. Those differences are retained below. Mean shaped reward is not a calibrated win probability, and no outcome here says which selected action would play better. Slot and target indexes distinguish actions with the same name. A value of -1 means no slot or target.

## Every measured condition

All 54 measured searches

| Scenario | Seed | Workers | Pool | Wall seconds | Simulations / second | Time ratio | Selected action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| duel | 7 | 1 | cold | 1.260795 | 9518 | 1.000 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 7 | 1 | warm | 1.219400 | 9841 | 1.000 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 7 | 2 | cold | 0.758656 | 15817 | 1.662 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 7 | 2 | warm | 0.638250 | 18801 | 1.911 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 7 | 4 | cold | 0.541184 | 22174 | 2.330 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 7 | 4 | warm | 0.381361 | 31466 | 3.197 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 42 | 2 | cold | 0.754850 | 15897 | 1.713 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 42 | 2 | warm | 0.599749 | 20008 | 2.090 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 42 | 4 | cold | 0.487546 | 24613 | 2.653 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 42 | 4 | warm | 0.317240 | 37826 | 3.952 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 42 | 1 | cold | 1.293305 | 9279 | 1.000 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 42 | 1 | warm | 1.253711 | 9572 | 1.000 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 99 | 4 | cold | 0.606181 | 19796 | 2.084 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 99 | 4 | warm | 0.423151 | 28359 | 2.812 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 99 | 1 | cold | 1.263309 | 9499 | 1.000 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 99 | 1 | warm | 1.189708 | 10087 | 1.000 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 99 | 2 | cold | 0.747588 | 16052 | 1.690 | Spark -> Frost Warden (slot 2, target 0) |
| duel | 99 | 2 | warm | 0.579214 | 20718 | 2.054 | Spark -> Frost Warden (slot 2, target 0) |
| gauntlet | 7 | 1 | cold | 1.800268 | 6666 | 1.000 | Spark -> Adept (slot 2, target 2) |
| gauntlet | 7 | 1 | warm | 1.829196 | 6560 | 1.000 | Spark -> Adept (slot 2, target 2) |
| gauntlet | 7 | 2 | cold | 1.016032 | 11811 | 1.772 | Spark -> Adept (slot 2, target 2) |
| gauntlet | 7 | 2 | warm | 0.915974 | 13101 | 1.997 | Spark -> Adept (slot 2, target 2) |
| gauntlet | 7 | 4 | cold | 0.628968 | 19079 | 2.862 | Spark -> Adept (slot 2, target 2) |
| gauntlet | 7 | 4 | warm | 0.479175 | 25043 | 3.817 | Spark -> Adept (slot 2, target 2) |
| gauntlet | 42 | 2 | cold | 0.976371 | 12290 | 1.819 | Spark -> Acolyte (slot 2, target 1) |
| gauntlet | 42 | 2 | warm | 0.868682 | 13814 | 2.218 | Spark -> Acolyte (slot 2, target 1) |
| gauntlet | 42 | 4 | cold | 0.597398 | 20087 | 2.972 | Spark -> Acolyte (slot 2, target 1) |
| gauntlet | 42 | 4 | warm | 0.419590 | 28599 | 4.592 | Spark -> Acolyte (slot 2, target 1) |
| gauntlet | 42 | 1 | cold | 1.775682 | 6758 | 1.000 | Spark -> Acolyte (slot 2, target 1) |
| gauntlet | 42 | 1 | warm | 1.926555 | 6229 | 1.000 | Spark -> Acolyte (slot 2, target 1) |
| gauntlet | 99 | 4 | cold | 0.762268 | 15742 | 2.732 | Spark -> Adept (slot 2, target 2) |
| gauntlet | 99 | 4 | warm | 0.556601 | 21559 | 3.884 | Spark -> Adept (slot 2, target 2) |
| gauntlet | 99 | 1 | cold | 2.082573 | 5762 | 1.000 | Spark -> Acolyte (slot 2, target 1) |
| gauntlet | 99 | 1 | warm | 2.162047 | 5550 | 1.000 | Spark -> Acolyte (slot 2, target 1) |
| gauntlet | 99 | 2 | cold | 0.903748 | 13278 | 2.304 | Spark -> Adept (slot 2, target 2) |
| gauntlet | 99 | 2 | warm | 0.761436 | 15760 | 2.839 | Spark -> Adept (slot 2, target 2) |
| boss | 7 | 1 | cold | 1.516430 | 7913 | 1.000 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 7 | 1 | warm | 1.590354 | 7545 | 1.000 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 7 | 2 | cold | 0.793772 | 15118 | 1.910 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 7 | 2 | warm | 0.596056 | 20132 | 2.668 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 7 | 4 | cold | 0.526255 | 22803 | 2.882 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 7 | 4 | warm | 0.445666 | 26926 | 3.568 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 42 | 2 | cold | 0.895159 | 13405 | 1.637 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 42 | 2 | warm | 0.651527 | 18418 | 2.381 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 42 | 4 | cold | 0.507003 | 23668 | 2.891 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 42 | 4 | warm | 0.363109 | 33048 | 4.272 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 42 | 1 | cold | 1.465553 | 8188 | 1.000 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 42 | 1 | warm | 1.551316 | 7735 | 1.000 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 99 | 4 | cold | 0.512744 | 23403 | 2.858 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 99 | 4 | warm | 0.345815 | 34701 | 4.387 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 99 | 1 | cold | 1.465216 | 8190 | 1.000 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 99 | 1 | warm | 1.517011 | 7910 | 1.000 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 99 | 2 | cold | 1.054738 | 11377 | 1.389 | Spark -> Frost Tyrant (slot 2, target 0) |
| boss | 99 | 2 | warm | 0.784463 | 15297 | 1.934 | Spark -> Frost Tyrant (slot 2, target 0) |

## Actual work and stopping

No worker failed, timed out or left unknown work in this attempt. All workers stopped at both the simulation cap and transition allowance. The retained JSON includes every assigned allowance, derived seed, worker duration, stopping reason, root visit count and raw value sum. The report validator reconstructs merged means from those sums and checks all 54 conditions. It does not rerun search or replace an incomplete result.

Work accounting

| Scenario | Seed | Workers | Pool | Simulations | Transitions | Unused simulations | Unused transitions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| duel | 7 | 1 | cold | 12000 | 60000 | 0 | 0 |
| duel | 7 | 1 | warm | 12000 | 60000 | 0 | 0 |
| duel | 7 | 2 | cold | 12000 | 60000 | 0 | 0 |
| duel | 7 | 2 | warm | 12000 | 60000 | 0 | 0 |
| duel | 7 | 4 | cold | 12000 | 60000 | 0 | 0 |
| duel | 7 | 4 | warm | 12000 | 60000 | 0 | 0 |
| duel | 42 | 2 | cold | 12000 | 60000 | 0 | 0 |
| duel | 42 | 2 | warm | 12000 | 60000 | 0 | 0 |
| duel | 42 | 4 | cold | 12000 | 60000 | 0 | 0 |
| duel | 42 | 4 | warm | 12000 | 60000 | 0 | 0 |
| duel | 42 | 1 | cold | 12000 | 60000 | 0 | 0 |
| duel | 42 | 1 | warm | 12000 | 60000 | 0 | 0 |
| duel | 99 | 4 | cold | 12000 | 60000 | 0 | 0 |
| duel | 99 | 4 | warm | 12000 | 60000 | 0 | 0 |
| duel | 99 | 1 | cold | 12000 | 60000 | 0 | 0 |
| duel | 99 | 1 | warm | 12000 | 60000 | 0 | 0 |
| duel | 99 | 2 | cold | 12000 | 60000 | 0 | 0 |
| duel | 99 | 2 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 7 | 1 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 7 | 1 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 7 | 2 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 7 | 2 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 7 | 4 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 7 | 4 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 42 | 2 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 42 | 2 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 42 | 4 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 42 | 4 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 42 | 1 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 42 | 1 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 99 | 4 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 99 | 4 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 99 | 1 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 99 | 1 | warm | 12000 | 60000 | 0 | 0 |
| gauntlet | 99 | 2 | cold | 12000 | 60000 | 0 | 0 |
| gauntlet | 99 | 2 | warm | 12000 | 60000 | 0 | 0 |
| boss | 7 | 1 | cold | 12000 | 60000 | 0 | 0 |
| boss | 7 | 1 | warm | 12000 | 60000 | 0 | 0 |
| boss | 7 | 2 | cold | 12000 | 60000 | 0 | 0 |
| boss | 7 | 2 | warm | 12000 | 60000 | 0 | 0 |
| boss | 7 | 4 | cold | 12000 | 60000 | 0 | 0 |
| boss | 7 | 4 | warm | 12000 | 60000 | 0 | 0 |
| boss | 42 | 2 | cold | 12000 | 60000 | 0 | 0 |
| boss | 42 | 2 | warm | 12000 | 60000 | 0 | 0 |
| boss | 42 | 4 | cold | 12000 | 60000 | 0 | 0 |
| boss | 42 | 4 | warm | 12000 | 60000 | 0 | 0 |
| boss | 42 | 1 | cold | 12000 | 60000 | 0 | 0 |
| boss | 42 | 1 | warm | 12000 | 60000 | 0 | 0 |
| boss | 99 | 4 | cold | 12000 | 60000 | 0 | 0 |
| boss | 99 | 4 | warm | 12000 | 60000 | 0 | 0 |
| boss | 99 | 1 | cold | 12000 | 60000 | 0 | 0 |
| boss | 99 | 1 | warm | 12000 | 60000 | 0 | 0 |
| boss | 99 | 2 | cold | 12000 | 60000 | 0 | 0 |
| boss | 99 | 2 | warm | 12000 | 60000 | 0 | 0 |

## Startup and transport controls

Startup is the measured process creation and readiness component inside cold wall time. Longest worker is the largest reported compute duration. Wall time less that duration is composite orchestration overhead, including startup when applicable. It is not pure IPC latency. The payload encode and decode probe runs in the parent before each search and is excluded from search wall time. Its bytes and timings describe serialization, not actual transport through a process queue.

Timing components and separate serialization probe

| Scenario | Seed | Workers | Pool | Startup seconds | Longest worker seconds | Composite overhead seconds | Payload bytes | Encode ms | Decode ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| duel | 7 | 1 | cold | 0.000000 | 1.260680 | 0.000115 | 1203 | 0.043200 | 0.060900 |
| duel | 7 | 1 | warm | 0.000000 | 1.219330 | 0.000069 | 1203 | 0.049500 | 0.041400 |
| duel | 7 | 2 | cold | 0.149118 | 0.606926 | 0.151730 | 2407 | 0.065700 | 0.059800 |
| duel | 7 | 2 | warm | 0.000000 | 0.637463 | 0.000787 | 2407 | 0.097700 | 0.081100 |
| duel | 7 | 4 | cold | 0.174496 | 0.365609 | 0.175575 | 4814 | 0.104300 | 0.097000 |
| duel | 7 | 4 | warm | 0.000000 | 0.380766 | 0.000595 | 4814 | 0.115500 | 0.108600 |
| duel | 42 | 2 | cold | 0.160207 | 0.593925 | 0.160925 | 2407 | 0.075100 | 0.068500 |
| duel | 42 | 2 | warm | 0.000000 | 0.599272 | 0.000477 | 2407 | 0.072700 | 0.064800 |
| duel | 42 | 4 | cold | 0.171314 | 0.315100 | 0.172446 | 4813 | 0.102600 | 0.091600 |
| duel | 42 | 4 | warm | 0.000000 | 0.316624 | 0.000616 | 4813 | 0.203600 | 0.199100 |
| duel | 42 | 1 | cold | 0.000000 | 1.293199 | 0.000106 | 1203 | 0.047500 | 0.044300 |
| duel | 42 | 1 | warm | 0.000000 | 1.253651 | 0.000060 | 1203 | 0.050300 | 0.043100 |
| duel | 99 | 4 | cold | 0.176513 | 0.428355 | 0.177826 | 4814 | 0.144000 | 0.129800 |
| duel | 99 | 4 | warm | 0.000000 | 0.422454 | 0.000696 | 4814 | 0.119500 | 0.111000 |
| duel | 99 | 1 | cold | 0.000000 | 1.263202 | 0.000108 | 1204 | 0.068200 | 0.056600 |
| duel | 99 | 1 | warm | 0.000000 | 1.189648 | 0.000060 | 1204 | 0.057000 | 0.041500 |
| duel | 99 | 2 | cold | 0.157116 | 0.589640 | 0.157948 | 2407 | 0.114200 | 0.064900 |
| duel | 99 | 2 | warm | 0.000000 | 0.578666 | 0.000547 | 2407 | 0.082100 | 0.070900 |
| gauntlet | 7 | 1 | cold | 0.000000 | 1.800182 | 0.000086 | 1618 | 0.026800 | 0.048800 |
| gauntlet | 7 | 1 | warm | 0.000000 | 1.829097 | 0.000098 | 1618 | 0.051900 | 0.049600 |
| gauntlet | 7 | 2 | cold | 0.154269 | 0.860930 | 0.155102 | 3237 | 0.088500 | 0.074700 |
| gauntlet | 7 | 2 | warm | 0.000000 | 0.915308 | 0.000666 | 3237 | 0.123000 | 0.075000 |
| gauntlet | 7 | 4 | cold | 0.166849 | 0.461347 | 0.167621 | 6474 | 0.119600 | 0.117000 |
| gauntlet | 7 | 4 | warm | 0.000000 | 0.478514 | 0.000661 | 6474 | 0.132700 | 0.118700 |
| gauntlet | 42 | 2 | cold | 0.150709 | 0.824865 | 0.151506 | 3237 | 0.077500 | 0.071800 |
| gauntlet | 42 | 2 | warm | 0.000000 | 0.867889 | 0.000793 | 3237 | 0.088600 | 0.086900 |
| gauntlet | 42 | 4 | cold | 0.179989 | 0.416346 | 0.181052 | 6473 | 0.287900 | 0.168100 |
| gauntlet | 42 | 4 | warm | 0.000000 | 0.418759 | 0.000831 | 6473 | 0.172100 | 0.132300 |
| gauntlet | 42 | 1 | cold | 0.000000 | 1.775562 | 0.000120 | 1618 | 0.070700 | 0.062500 |
| gauntlet | 42 | 1 | warm | 0.000000 | 1.926456 | 0.000099 | 1618 | 0.071900 | 0.060700 |
| gauntlet | 99 | 4 | cold | 0.210952 | 0.550232 | 0.212037 | 6474 | 0.163100 | 0.153300 |
| gauntlet | 99 | 4 | warm | 0.000000 | 0.555553 | 0.001047 | 6474 | 0.196200 | 0.182100 |
| gauntlet | 99 | 1 | cold | 0.000000 | 2.082467 | 0.000106 | 1619 | 0.083600 | 0.068400 |
| gauntlet | 99 | 1 | warm | 0.000000 | 2.161972 | 0.000075 | 1619 | 0.058100 | 0.051500 |
| gauntlet | 99 | 2 | cold | 0.144777 | 0.757991 | 0.145758 | 3237 | 0.108800 | 0.082800 |
| gauntlet | 99 | 2 | warm | 0.000000 | 0.760844 | 0.000592 | 3237 | 0.084700 | 0.086400 |
| boss | 7 | 1 | cold | 0.000000 | 1.516342 | 0.000088 | 1504 | 0.027000 | 0.047500 |
| boss | 7 | 1 | warm | 0.000000 | 1.590285 | 0.000068 | 1504 | 0.086800 | 0.071200 |
| boss | 7 | 2 | cold | 0.150887 | 0.642074 | 0.151698 | 3009 | 0.109700 | 0.106500 |
| boss | 7 | 2 | warm | 0.000000 | 0.595509 | 0.000546 | 3009 | 0.126000 | 0.104100 |
| boss | 7 | 4 | cold | 0.159080 | 0.366232 | 0.160023 | 6018 | 0.124000 | 0.126100 |
| boss | 7 | 4 | warm | 0.000000 | 0.444629 | 0.001037 | 6018 | 0.170200 | 0.152300 |
| boss | 42 | 2 | cold | 0.203074 | 0.691277 | 0.203882 | 3009 | 0.113600 | 0.097600 |
| boss | 42 | 2 | warm | 0.000000 | 0.650983 | 0.000544 | 3009 | 0.085600 | 0.069000 |
| boss | 42 | 4 | cold | 0.174041 | 0.332113 | 0.174890 | 6017 | 0.174400 | 0.154500 |
| boss | 42 | 4 | warm | 0.000000 | 0.362434 | 0.000675 | 6017 | 0.133300 | 0.201900 |
| boss | 42 | 1 | cold | 0.000000 | 1.465423 | 0.000130 | 1504 | 0.070100 | 0.055100 |
| boss | 42 | 1 | warm | 0.000000 | 1.551246 | 0.000070 | 1504 | 0.075700 | 0.053900 |
| boss | 99 | 4 | cold | 0.169872 | 0.341722 | 0.171022 | 6018 | 0.161300 | 0.141000 |
| boss | 99 | 4 | warm | 0.000000 | 0.344973 | 0.000841 | 6018 | 0.169300 | 0.122700 |
| boss | 99 | 1 | cold | 0.000000 | 1.465097 | 0.000119 | 1505 | 0.085700 | 0.072100 |
| boss | 99 | 1 | warm | 0.000000 | 1.516945 | 0.000066 | 1505 | 0.064900 | 0.051400 |
| boss | 99 | 2 | cold | 0.164589 | 0.889299 | 0.165439 | 3009 | 0.086300 | 0.072800 |
| boss | 99 | 2 | warm | 0.000000 | 0.783607 | 0.000855 | 3009 | 0.115300 | 0.107400 |

## Environment and evidence

Windows on an AMD Ryzen 7 7800X3D with 8 cores and 16 logical CPUs. Competing agent tests and rendering were paused. Ordinary applications remained active and untouched. Before the coordinated window aggregate CPU samples ranged from 33.7 to 41.7 percent. This is a shared machine measurement, not an isolated scaling result.

Measured source: 7dac590cfd27386b848fadef31a8afa46206aab1. Protocol and implementation were committed before this first attempt. Source identity stayed unchanged during measurement. The source hash map and all original timestamps remain in the retained JSON. This report is a later presentation of those saved data, not another experiment.

Python: 3.11.8 (tags/v3.11.8:db85d51, Feb  6 2024, 22:03:32) [MSC v.1937 64 bit (AMD64)]. Platform: Windows-10-10.0.26200-SP0. Started: 2026-09-27T08:28:55.475712+00:00. Ended: 2026-09-27T08:29:47.602722+00:00.

The root states are public synthetic examples. This study covers one work allowance, one horizon, three initial states and three seeds on one machine. It does not measure full game throughput, deployment latency, cross platform reproducibility or compilation. Earlier benchmark and baseline studies remain separate and unchanged.

Validate and render the retained result without running the study:

```sh
python tools/render_parallel_scaling.py --check
```
