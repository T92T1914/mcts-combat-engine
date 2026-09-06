# Historical results before the action-identity repair

This 2026-09-05 wall-clock run describes earlier code with a known search action-identity defect. It is retained for provenance, not as a current performance claim.

60 games per policy per scenario, game seeds paired across policies; 120 ms of search per decision, single process.
Python 3.11.8 on Windows-10-10.0.26200-SP0, 16 logical CPUs; AMD Ryzen 7 7800X3D (8 cores / 16 threads), 64 GB RAM, Windows 11 Pro.
Run on 2026-09-05 in 7.1 min.

| scenario | random | greedy | mcts (120 ms) | search vs best baseline |
|---|---|---|---|---|
| duel | 90% (80–95) · 20.2r | 35% (24–48) · 16.2r | **100% (94–100) · 16.6r** | z = 2.51 vs random |
| gauntlet | 55% (42–67) · 23.4r | 32% (21–44) · 17.2r | **95% (86–98) · 16.9r** | z = 5.06 vs random |
| boss | 20% (12–32) · 25.9r | 3% (1–11) · 17.0r | **57% (44–68) · 22.4r** | z = 4.13 vs random |

*win % = clean wins (95% Wilson interval) · Nr = average rounds to win, when it won · bold = best in row*
