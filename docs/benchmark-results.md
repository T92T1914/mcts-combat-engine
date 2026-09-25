# Recorded fixed budget results, September 6

30 games per policy per scenario, game seeds paired across policies; 3000 simulations per decision, search seed 42, horizon 5, 60 second safety cap, single process.
Python 3.11.8 on Windows 10-10.0.26200 SP0, 16 logical CPUs; AMD Ryzen 7 7800X3D; Windows 11; 64 GB RAM.
Run on 2026-09-06.

| scenario | random | greedy | mcts (3000 sims) | search vs best baseline |
|---|---|---|---|---|
| duel | 90% (74 to 97) · 19.7r | 37% (22 to 54) · 16.9r | **100% (89 to 100) · 16.2r** | z = 1.78 vs random |
| gauntlet | 57% (39 to 73) · 24.2r | 37% (22 to 54) · 17.5r | **100% (89 to 100) · 17.2r** | z = 4.07 vs random |
| boss | 27% (14 to 44) · 25.0r | 0% (0 to 11) | **50% (33 to 67) · 22.5r** | z = 1.86 vs random |

*win % = clean wins (95% Wilson interval) · Nr = average rounds to win, when it won · bold = best in row*

The original command was `python benchmark.py 30 --sims 3000 --seed 42 --markdown docs/benchmark-results.md`. Game seeds are 0 to 29. These measurements predate the RNG-isolation repair. Keep them separate from new runs rather than overwriting this record with the current command.

The earlier runner shared one random stream between policy choices and environment outcomes. The benchmark also created search once before its scenario loop, contrary to the earlier description here that it was seeded once per scenario. The current runner separates policy randomness, and the current benchmark restarts search for each scenario. The recorded aggregates above have not been rerun under that new protocol. Different actions can still take different stochastic paths even with separate streams.

Matched pre repair / repaired search wins: duel 29/30 → 30/30; gauntlet 30/30 → 30/30; boss 16/30 → 15/30. The fix establishes legal action identity, not an across the board win rate improvement. Boss average shaped score changed from 0.6310 to 0.6191. Thirty games and one search seed are a smoke benchmark, not a tuning study. The displayed two proportion z scores are descriptive independent sample approximations; they do not exploit pairing and are not evidence of a population level advantage.

The boss smoke test formerly required a 25 point margin over random. It now requires beating both baselines, winning over 40%, and exceeding random’s mean score. Correctness is tested separately by checking every simulated move for legality and stable card identity. This test change is explicit because a one game difference should not be concealed as an improvement.

Raw [before](benchmark-before.json) / [after](benchmark-after.json) results include batch elapsed time. Other audits ran concurrently; those times are not a throughput comparison.
