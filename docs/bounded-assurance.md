# Bounded model and evidence assurance

The deterministic assurance corpus checks selected input limits, retained
evidence joins, text preservation and public model boundaries. Its expectations
are declared separately from the implementation. It supplements the existing
parser, action, replay, reference, recovery and passive inspection tests.

Run it from a source checkout with Python 3.11 or later:

```text
python -m unittest discover -s tests -p "test_bounded_*_assurance.py" -v
```

The corpus uses the standard library. It performs no search or scientific
sampling. Passive recovery and rendering cases guard recording, replay,
subprocess and retry entry points. The tests retain originals in temporary
directories and compare their bytes and modification times after inspection.
The checkout tests are development inputs and are not installed with the engine
or included in the companion.

## Declared cases

Content cases use `game.episode_record.load_content`, including its captured-byte
staging and actual loader. Seven neighboring pairs cover 128/129 unique cards,
128/129 deck entries, 16/17 scenarios, 8/9 enemies, 128/129 character card names,
128/129 character combatant names and 2048/2049 character descriptions. Exact
upper bounds are admitted when the rest of the content is valid. Upper bound
plus one is refused before the staged loader or a scenario factory runs. A
baseline is retained alongside those 14 boundary cases. The separate total-rule
limit remains intact. An oversized description can be refused by the general
JSON string envelope before field-specific validation.

Ten recovery cases use the repository's real synthetic capture fixture. Each
stdout/stderr stream has equal, smaller and larger observed-length claims.
Equal untruncated length is consistent. Observed bytes smaller than retained
bytes, or larger with truncation false, are contradictions. A complete receipt
cannot claim truncated transport. An incomplete receipt may retain a truncated
fragment while its outcome and work remain unknown. Independent work and timing
sidecar disagreements are contradictions. Tests assert trial classifications
and inventory consistency, rather than treating report delivery as completion.

Text cases compare independently written literal canonical field bytes and
decoded values for quotation marks, angle brackets, ampersands, a non-BMP
character and an escaped lone surrogate with a JSON control character. Both
HTML editions preserve typed JSON fragments while keeping supplied text passive.
The surrogate enters as an ASCII JSON escape, not malformed UTF-8. A whitespace
and key-order variant has the same decoded values and a different captured-byte
identity. Existing numeric representation tests remain separate controls.

Public pip cases enumerate all 36 nonnegative normal/power pip pairs occupying
at most seven slots, costs zero through 14 and matching/nonmatching elements.
The 1,080 admission cases use the independent effective resource expression
`p + m*q`, where `m` is two for a matching element and one otherwise. The 492
affordable cases check power-first payment with a closed-form integer oracle.
Seventy-two full-round cases check regeneration at probability endpoints zero
and one, including the seven-slot cap. Two card-play rounds connect affordability,
odd matching cost, payment and subsequent regeneration. These cases use the
public model without search, attacks, drain or boss rules.

Rejected neighbors, contradictory sidecars, unaffordable actions, exact equality,
full slots and text which resembles markup serve as negative controls. A passing
corpus does not demonstrate a new defect or justify changing model behavior.
If a case reveals a discrepancy, its minimal reproduction and adverse result
must remain available before a narrowly justified repair.

## What the evidence establishes

The selected source, installed engine and companion code, fixture constructors,
test code and independently declared oracles are trusted executable inputs.
Custom JSON, saved records, names, labels, protocol and receipt claims, raw
streams, sidecars, digests and runtime or ownership labels are untrusted data.
Caller-selected paths and the existing filesystem are operating assumptions.

Structural admission and cross-file agreement establish consistency within the
declared scope. A measured digest identifies bytes. Mutually supplied hashes and
internally consistent claims do not authenticate a producer or prove that an
operating system contained a process. Recovery reports preserve that distinction.
The exact source gates described in [model compatibility](model-compatibility.md)
remain required for replay and reference evaluation.

This finite corpus covers the listed properties. It does not cover every malformed
input, certify security, establish statistical completeness or measure improved
decision quality. Ordinary hosted Linux consumer checks and process-group
timeouts do not establish Linux memory enforcement. Windows managed execution
keeps its separate [ownership contract](managed-encounters.md).
