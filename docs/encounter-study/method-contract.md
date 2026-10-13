# Encounter comparison protocol

Status: method approved before any experimental collection. Source and seed manifests must be captured before each phase. No pilot or deciding outcomes have been observed when this contract was written.

## Question and treatment

Does the accepted first action reference advantage of existing horizon one sequential halving translate to terminal wins when that policy is used repeatedly through complete encounters, compared with existing horizon one UCT?

The treatments include each policy's existing allocation and final action rule. This study does not isolate a causal mechanism, change rewards, add deeper halving or promote a default.

Use the exact shipped duel, gauntlet and boss configurations. These are three fixed modeled presets, not a random sample of encounter families. All content bytes and implementation identities are frozen. Each encounter receives a fresh state, environment RNG, search RNG and managed search owner. No owner is reused across encounters.

Per decision: horizon 1, 32 simulations and 32 transitions, serial clockless execution, exploration 1.2 and no priors. Maximum encounter length is 30 rounds. The unchanged simulator, reward, physical actions and dynamic legality apply. Count actual simulations, transitions, unused allowance, stop reasons and uniform fallback decisions.

## Phases, seeds and feasibility

The exploratory phase contains exactly 4 seed blocks, 24 encounters. It evaluates only feasibility, operational reliability, trace sizes and cost. It supplies no tuning data or primary outcome estimate used to select a policy or deciding sample size.

Pilot environment seeds are independent uniform draws with replacement from [2**59,2**60). Pilot search seeds use [2**60,2**61). Deciding environment seeds use [2**61,2**62); deciding search seeds use [2**62,2**63). Use the operating system backed SystemRandom for these draws. Seed collisions across blocks are allowed. Labels are separate even if magnitudes repeat.

Each block carries paired initial environment and search seed labels across both policies and all three presets. Each encounter creates separate RNG objects. The two policies can consume different random draws after decisions diverge. Paired labels are not evidence of matched later random events. Dependence within a block is allowed. Blocks are independently generated under the declared seed experiment.

Order the presets duel, gauntlet, boss. Alternate policy order by block parity. The deciding list is frozen before deciding collection. Do not replace failed seeds, extend collection for a favorable result or tune on deciding observations.

Tentative deciding size is 512 blocks, 3072 encounters. Admit it only if the fixed pilot has no operational unknown or underfunded decision, maximum observed pilot trial elapsed times 3072 projects to at most 1800 seconds, projected raw corpus is at most 512 MiB, and available disk is at least three times that projection. These are feasibility estimates, not guarantees for unseen tails. If the pilot fails those conditions, choose a smaller count before drawing deciding seeds, explicitly record weaker precollection interval precision, or retain a blocked/incomplete study. Pilot terminal outcomes do not determine this decision.

A hard 10 second trial wall bound and a separate total collection deadline apply. Pilot total is 240 seconds, deciding total 1800 seconds. Use the retained external Windows Job owner, 512 MiB aggregate committed memory and five second retirement allowance. No new trial starts after the declared total deadline. All intended slots remain in the inventory if an operation stops. A caller supplied bound description does not itself prove that ownership; retain the actual Job receipt.

If 512 blocks fail only the cost or disk projection, choose the largest even block count at most 512 that satisfies the same projections. Use the maximum observed whole trial directory size, including retained stdout and the admitted episode, for disk estimation. At least two blocks are required by the variance formula. This deterministic sizing rule is fixed before the pilot. It does not read terminal win counts or shaped scores.

## Endpoint and missingness

Primary Y is one only for exact terminal_result == 1 by round 30. An admitted terminal loss has Y zero. An admitted ongoing round cap also has Y zero for this endpoint, but is not classified as a terminal loss. Shaped score is descriptive, not the terminal endpoint.

Any operational timeout, error, source/content mismatch, invalid record, retirement failure, missing episode or underfunded decision leaves Y unknown. Unknown work is unavailable, not zero. Retain all intended denominators, raw diagnostic output, receipts, traces and adverse cases. No incomplete run produces a complete inference.

## Primary analysis

For each independent block i, B_i is one third of the sum over the three presets of Y_halving minus Y_uct. It lies in [-1,1]. The estimand is the equal weighted terminal win difference for these three fixed presets under this seed experiment. Positive favors sequential halving.

Let k_i=3B_i, S=sum(k_i), Q=sum(k_i**2), and N be the frozen deciding block count. Calculate mean=S/(3N) and unbiased variance=(NQ-S**2)/(9N(N-1)). Retain N,S,Q and all six binary outcomes per block.

One primary interval is prespecified. Alpha is 0.05. Radius is sqrt(2*variance*log(4/alpha)/N) + 14*log(4/alpha)/(3*(N-1)). Clip endpoints mean plus or minus radius to [-1,1]. This is the empirical Bernstein bound derived from Maurer and Pontil Theorem 4 by mapping B to (B+1)/2 and allocating alpha/2 to each tail. [Original paper](https://arxiv.org/pdf/0907.3740).

At N=512 the minimum possible radius is about 4.002 percentage points. There is no postcollection switch to a narrower interval and no multiple primary method selection.

The independently authored checker computes exact integer moments and conservative rational enclosures for the logarithm and square root in this same formula. This numerical enclosure is fixed before collection and introduces no epsilon or alternative statistical method. Its source hash is retained in the protocol freeze.

If any intended outcome is unknown, withhold primary inference. Report deterministic bounds by allowing each unknown Y to vary over [0,1], with the original intended denominators. Do not condition inference on successfully completed encounters.

Interpretation is fixed:

* Lower endpoint above zero supports a positive equal weighted difference in this experiment.
* Upper endpoint below zero supports an adverse equal weighted difference.
* An interval containing zero is inconclusive about direction. It does not establish equality or absence of benefit.
* Any operational unknown withholds primary inference.

Per preset paired outcome cells, terminal losses, round caps, encounter lengths, shaped scores, actual total work and elapsed costs are descriptive secondary outputs. Rounds conditional on winning must be labeled. No additional confidence claims are issued for presets. Equal per decision allowances are not equal total execution costs. A directional signal is not proof of general stronger play, practical value, optimality or default promotion.

## Acceptance

Independent source review challenges versioned admission, physical identities, actual work, source integrity, timeout retirement and output boundaries. Independently authored analysis reconstructs outcomes from the retained episodes rather than trusting the collector summary. Relevant tests, current required CI and an actual installed engine plus separate companion journey verify delivery. Historical releases are retained as historical evidence unless rerun.

