# Use the saved-episode example kit

Download `episode-examples.zip` from the project page when you already have an
installed engine and want to work with a saved episode. Extract the complete ZIP
into a fresh directory. The inspection and decision entries come with matching
`game/` helpers, so there is no need to assemble them from a checkout.

The kit requires Python 3.11 or later and a selected installation of
`mcts-combat-engine`. It contains no engine or wheel. Use the Python executable
for that installation. If you need to install the engine first, follow the
[repository setup](https://github.com/T92T1914/mcts-combat-engine#run-it).
The full checkout remains an alternative for running these examples.

## Inspect or make a fresh decision

Keep the two entries and the complete `game/` directory together. You can move
the whole extracted directory. Do not add a local `engine/`, which would shadow
the installed engine. No Git, checkout `PYTHONPATH`, original cards/scenarios or
earlier environment replay is needed for either command.

From an unrelated working directory, supply the installed Python, entry and
existing episode paths. Use PowerShell 7.4 or later for these byte-preserving
redirection examples:

```powershell
& 'C:\work\engine-env\Scripts\python.exe' 'C:\work\episode-examples\inspect_episode.py' 'C:\work\custom-episode.json' > episode.html
& 'C:\work\engine-env\Scripts\python.exe' 'C:\work\episode-examples\decide_episode.py' 'C:\work\custom-episode.json' --step 1 --seed 19 --sims 4 --horizon 2 > decision.json
```

Use paths for your own installation, extracted kit and record. Inspection emits
a self-contained HTML reading artifact and performs no search or replay. The
decision command selects the existing zero-based `/steps/1/state` boundary and
makes one fresh search with the stated seed and work allowance. It does not
continue the recorded policy's random stream or refill the saved hand.

Use fresh output filenames and keep stderr separate. Shell redirection can
create or overwrite its target even if a command fails. PowerShell 7.4+ preserves
native stdout bytes; older Windows PowerShell can change the encoding. See
[Microsoft's redirection documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection).
A POSIX shell also supports byte-preserving redirection.

Read the included [inspection guide](episode-inspection.md) and
[decision guide](episode-decision.md) for controls, validation, output fields and
limits. Their checkout setup sections describe the alternative source layout.
The inspection guide's environment-replay link opens repository documentation
online, pinned to this kit's source commit. Recording and environment replay
require their full checkout setup and are not kit commands. Original content
and matching stored runtime labels are unnecessary for passive inspection.

## File identities and compatibility

`episode-examples.zip.sha256` names the whole downloaded ZIP. For example:

```powershell
Get-FileHash .\episode-examples.zip -Algorithm SHA256
Get-Content .\episode-examples.zip.sha256
```

Compare that digest with the sidecar. `manifest.json` gives the source commit and
tree, each emitted payload's size and SHA-256, and separate reference engine
identities. It does not hash itself. Those engine files are reference code from
the source revision, not files shipped in this kit or proof of your imported
installation. A version string alone does not establish equal code.

Every executable file is the literal committed source. The inspection guide has
one archive-only change: its replay link names the captured commit online. The
manifest records the canonical and emitted guide identities and that exact
transformation. No repository guide is rewritten by generation.

The commands retain their existing validators and observed implementation
identities. Arbitrary cross-version compatibility is not promised. Inspection
does not authenticate a record or verify its stored runtime claims. A fresh
decision's sampled values are shaped search rewards, not win probabilities or
proof that it improves on the stored action. Hash agreement establishes byte
equality with the compared reference, not origin authentication.

## Generate from source

For development, run this from a clean committed Git checkout:

```text
python tools/build_episode_examples.py
```

It writes only `_site/episode-examples.zip` and its sidecar. The existing site
builder also generates them. Source must have no tracked or nonignored
untracked changes. Windows CRLF worktree files are accepted only when their
UTF-8 CRLF-to-LF mapping equals the literal Git blob. Archive code comes from
those Git blobs, without importing the example or running a search.

The same revision and inputs produce identical output bytes. A test-merge or
main commit can change the manifest and pinned guide link even when executable
payload is identical. Source, included code, reference engine and whole-ZIP
identities are separate. A generation or write error fails the build. The two
output writes are not atomic as a pair, so a failed pair must not be published.
