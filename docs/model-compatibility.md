# Model compatibility after the exact health threshold repair

`EnrageBelowHalf` applies at round end to a living boss whose current HP is
strictly below 50 percent of its maximum. The integer comparison is
`2 * hp < max_hp`. For maximum 5 and current HP 2, the rule now adds a blade.
For maximum 4 and current HP 2, exact equality still adds none. Dead combatants,
nonboss combatants and other rule events do not trigger it.

The previous comparison, `hp < max_hp // 2`, missed the positive floor-half value
for odd maximums. Supported custom JSON can contain those maximums. This repair
changes their simulated behavior, so their future transitions and search rewards
can differ. It does not change the search objective, policy or rule serialization.

## Saved episodes and fresh decisions

Episode compatibility requires the full observed implementation and runtime
identity, including the raw `rules.py` hash. A pre-repair episode therefore
returns `incompatible` when replayed against the repaired implementation, before
the replay creates its scenario. Keep the original record, source identity and
historical replay receipt. An even-maximum input that behaves the same does not
override this complete-source requirement.

Passive validation and inspection can still display a valid historical record
without running its simulator. They check structure and consistency rather than
authenticating its origin. The source hashes bind observed bytes, not the author
or executing code.

A fresh decision from a saved state reconstructs that state and uses the current
model. Its report retains the saved provenance and compares the stored and
current implementation identities. A different engine hash map remains an
explicit difference. This operation is a new decision under the repaired model.
It is not a replay or proof that the historical policy made the saved choice.

New episodes recorded with the repaired engine and matching companion can be
replayed under their matching implementation and runtime. A package version alone
does not establish that match. A source checkout, installed wheel, different
Python runtime or mismatched companion can carry different observed identities.

## Existing finite references

The physical one-round, three-enemy, sum-convolution and two-round adaptive
references continue to exclude every state with a boss rule. Adding the repaired
engine's source maps does not extend those model domains or price an enraged boss.
Within their existing domains, the changed rule is absent and cannot fire.

Reference source admission compares a complete nine-file raw hash map with an
explicitly qualified declaration. The seven historical declarations remain
unchanged. The repair adds two separately checked declarations:

| Source declaration | `rules.py` SHA-256 |
| --- | --- |
| Exact-half canonical LF | `61c52b9ad9f54a5f37b4e1a063dd285a3f0a07a8263a038241161439005ce211` |
| Exact-half Windows CRLF | `0a098f932f51c8f529cdb37c2b296464fe43b41d1b341acbcf5da9425fe83d1c` |

Each new declaration retains the other eight members of its corresponding
historical managed map. The source check binds the actual current files, proves
the LF and CRLF projections agree, and checks that the sole historical source
change is the stated threshold predicate. Runtime admission never normalizes an
unknown map or accepts a file only because its syntax tree appears equivalent.
Unknown changed, missing, extra or mixed members cause `engine_mismatch` before
reference arithmetic. A map that exactly recreates a separately qualified
historical declaration remains that recognized complete historical map.

Historical complete reference reports retain their own declared source maps.
The passive readers continue to admit those declarations and reject a complete
report crossed with a different map. Saved mismatch refusals remain readable
without pretending that they are completed calculations. Reading these reports
does not recompute their values or authenticate their producer.

The identity test retains the exact pre-repair `engine/rules.py` body in
`tests/fixtures/pre-exact-half-rules.json`. Its
base64 field preserves literal source bytes through text checkout conversions.
The test verifies the decoded length, SHA-256 and Git blob ID against the
pre-repair declaration from
[the retained rules source at commit 6f1a870](https://github.com/T92T1914/mcts-combat-engine/blob/6f1a870307f62cd73634fcbf5603781734151136/engine/rules.py).
It uses those retained bytes for the
historical line-ending check, rather than equating the changed current rule with
an old hash. The fixture is source evidence and is never imported as executable
code.

## Delivery and evidence limits

Build a new companion from the repaired clean source and use the matching
externally installed engine. The companion manifest binds its exact source commit,
tree, payload and engine files. Existing installed checks reject an engine that
does not match that manifest. Preserve earlier archives, records, reference
reports and scientific studies as historical evidence with their original
identities. The shipped even-maximum boss remains the existing fixture; it does
not establish that every historical custom input is behaviorally unchanged.

The threshold corpus and public JSON round case establish the repaired boundary.
The finite reference comparisons establish agreement only within their admitted
domains. Environment replay establishes consistency under a matching simulator,
not model validity, optimal decisions or authenticity. Local tests, installed
consumer acceptance and remote CI are separate checks and must retain their
actual outcomes, including refusals and skipped cases.
