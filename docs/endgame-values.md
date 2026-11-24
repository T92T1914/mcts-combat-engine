# Exact endgame values, node counting result

I wanted to measure how often the search picks the action with the best exact chance of winning. That needs an exact solver, and an exact solver is only worth building if enough saved states are small enough to solve. This document records the counting pass that checks that first. The answer is that almost none are, so I stopped before writing a solver.

## What was counted

`tools/endgame_node_count.py` plays the engine's own `advance_round` under every chance outcome and counts what a solver would have to visit. It reports two numbers for each state.

1. Nodes, the number of distinct states that can follow, merged when two paths reach the same state.
2. Branches, the number of chance outcomes expanded. This is the work a solver with a transposition table does, because it expands each distinct state once.

The chance model is the one the search simulates. The hand is fixed and nothing refills it inside the tree. A comparison of a uniform draw with a threshold has two outcomes, an integer draw has one outcome per integer, and a weighted choice has one outcome per option with weight above zero. A draw the tool does not branch makes it raise, so a new kind of draw cannot be counted by accident. `tests/test_endgame_node_count.py` checks two things. Every round sampled with seeded generators lands inside the enumerated outcomes, and two small trees match counts worked out by hand.

The states are every decision of 18 recorded episodes, the three encounters with environment seeds 1 to 6, search seed equal to the environment seed, 30 rounds, 16 simulations and horizon 4. That is 425 states. The tree runs to a win, a loss or the round limit of 30. Counting stopped at 1,000,000 branches or 200,000 nodes. `docs/endgame-values/node-counts.json` keeps one row per state with its state digest, rounds left, status, nodes and branches.

## Result

| Encounter | States | Fit under 1,000,000 branches | Over by branches | Over by nodes |
| --- | --- | --- | --- | --- |
| duel | 125 | 0 | 61 | 64 |
| gauntlet | 142 | 3 | 108 | 31 |
| boss | 158 | 3 | 56 | 99 |
| all | 425 | 6 | 225 | 194 |

Six states fit, and two of those need 100,000 branches or fewer. Five of the six have one or two rounds left, so the round limit cuts the tree, and the sixth has eight rounds left but one enemy action finishes it. No state from the duel fits. Every state that does not fit passed the cap within its first four rounds, and 50 passed it inside the first round alone.

The reason is the damage range. A card that deals 440 to 520 and an enemy hit of 340 to 470 give thousands of distinct health pairs after one round, and each of those branches again. Merging identical states does not help much, because the health values really are different.

## What this closes

The extension asked for an exact chance of winning for endgame states that fit under a stated cap, and it said to close on purpose if too few states fit to say anything. Six states cannot give an interval worth reading for how often the search is exactly right. So I did not write a protocol with a cap or a solver. The queue records the second and third steps as closed on purpose.

## Limits

1. The counts use the search's own model, with no hand refill. The real game refills the hand, which would only make the trees larger.
2. The branch cap of 1,000,000 and the node cap of 200,000 are what I ran. A larger cap would admit more states, but the count of branches passes the cap within a few rounds, so a cap ten times larger would not change the shape of the result. I did not test one.
3. A solver that collapses states by what can still matter, for example treating player health as irrelevant when the enemies cannot kill within the rounds left, could solve more states. I did not build or count that, and it would need a proof that the collapse is exact.
4. This says nothing about how well the search plays. It says only that its decisions cannot be checked against the exact full depth answer on these states.
5. The default search, the reward constants, every retained result and the dependency list are unchanged.
