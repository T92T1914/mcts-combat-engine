# One installed episode with Linux container ownership

`linux_episode.py` supplies a small record-and-replay consumer to an existing
local Docker daemon on Linux. It verifies the exact container's kernel controls
and process membership before transferring the public payload, installing the
engine or recording an episode. The Windows managed encounter command keeps
its existing process owner and receipt format.

This command requires an ordinary Linux actor with existing access to the local
Unix Docker endpoint, cgroup v2 with memory, swap and PID controls, and a host
proc/cgroup view that reconciles with the daemon's process identities. The
currently qualified actor is UID/GID 1001. Unsupported or ambiguous environments
refuse before installation or policy admission. The command does not install
Docker, start services, change groups or repair host configuration. Access to a
Docker daemon is substantial existing authority. The command uses a fixed,
restricted configuration rather than exposing arbitrary daemon options.

## Supply the two matching parts

Download the complete
[episode companion](https://t92t1914.github.io/mcts-combat-engine/episode-companion.zip)
and [checksum sidecar](https://t92t1914.github.io/mcts-combat-engine/episode-companion.zip.sha256),
then compare their SHA-256.
Read the companion's `manifest.json` to obtain its source revision and acquire a
matching engine wheel separately. For example, ordinary pip can build that
revision's source archive into a fresh wheel directory:

```sh
python3 -m pip wheel --no-deps --wheel-dir wheels \
  https://github.com/T92T1914/mcts-combat-engine/archive/SOURCE_COMMIT.zip
```

Replace `SOURCE_COMMIT` with the exact manifest value. Keep the wheel's original
filename. This acquisition happens outside the managed container's accounting.
The companion contains no engine or wheel. Its manifest and checksum support
byte consistency, while ordinary downloaded files do not authenticate their
publisher by themselves.

Extract the complete companion into a fresh directory. Run its controller from
any working directory with absolute paths and a fresh output directory:

```sh
python3 /path/to/companion/linux_episode.py \
  --wheel /path/to/wheels/mcts_combat_engine-0.1.0-py3-none-any.whl \
  --companion /path/to/episode-companion.zip \
  --output /path/to/new-linux-episode
```

The controller separately acquires the public official Python 3.11 slim image
with a 90-second request deadline and resolves its immutable image ID. Supply
`--image-id sha256:...` only when that exact image is already available and
matches the locally resolved official Python 3.11 slim selector. Creation
disables pulling. Image acquisition, Docker clients,
daemon and runtime shim costs are outside the container's memory boundary.

## What the bounds mean

The consumer requests 256 MiB of cgroup v2 memory, no swap, 64 PID slots including
threads and one CPU of quota. It verifies the literal controls against the
created container and pinned root process, including a reconciled in-container
view. Memory accounting includes applicable anonymous memory, file cache, tmpfs
and kernel charges for the container and descendants. Shared-page attribution
and costs outside the group remain outside this scope. `memory.max` can permit
temporary overage. Sampled usage is not a lifetime peak guarantee.

The trusted root runs as UID/GID 1001 with capabilities dropped and
no-new-privileges. It has private PID/cgroup namespaces, no network, read-only
root, a 32 MiB private temporary filesystem and disabled daemon logging. No host
directory, socket, proc or cgroup mount is exposed. Only ordinary bounded public
payload files are copied into the exact container. Input is limited to 256 files
and 16 MiB. These are controls for trusted companion execution, not a security
promise for arbitrary hostile code.

The default admitted-work wall allowance is 30 seconds, covering payload
transfer, installation and execution. `--wall-seconds` permits 1 through 30
seconds. Retained stdout and stderr each have 64 KiB allowances, with a combined
128 KiB allowance. The controller stops excess output and preserves explicit
observed and retained counts. The three named result files have a separate
2 MiB aggregate artifact allowance. A separate ten-second cleanup interval
observes retirement of the exact owned container.

An independent root alarm exits after 60 seconds even when the external
controller is lost. Exit is an observable event, not a promise about instant
kernel completion. A stopped container object may remain until explicit
recovery. No detached watcher or recurring cleanup job is created.

## Inspect the result or recover an interrupted controller

The small consumer installs the engine wheel into an external environment inside
the admitted container, relocates the complete companion and checks literal
engine bytes and module origins. It records at most two rounds with two
simulations per decision and horizon one, then replays the saved actions with
new search guarded against execution. Its fixed seeds are operational acceptance
inputs. The journey makes no policy superiority or PR59 study claim.

The fresh output directory contains `ownership.json`, bounded stream logs and,
after a complete journey, `record.json`, `replay.json` and `consumer.json`.
Inspect the ownership receipt without running a policy, replay or retry:

```sh
python3 /path/to/companion/recover_linux.py /path/to/run/ownership.json
```

The inspection reports contradictions and explicitly distinguishes receipt
consistency from authentication. Initial and incomplete receipts can be
consistent without claiming completion. Explicit empty or zero values remain
known values. A complete outcome requires successful admitted work and the
required observed cleanup.

To request retirement of only the recorded owned container, add
`--cleanup-owned-container`. The owner rechecks its exact full container ID,
nonce, name, fixed configuration and current process/cgroup relationship.
Contradictory or ambiguous ownership refuses cleanup. The original receipt is
preserved, and cleanup produces a separate result on stdout. Ordinary JSON is
not authenticated authority. Use a receipt whose origin you trust. Recovery
does not search, replay, retry, resume or clean up other daemon objects.

## Acceptance boundary

The source contains a finite native CI consumer and controlled memory, PID,
descendant/session, output, wall, cancellation and controller-loss experiments.
Memory and PID enforcement require actual kernel event observations. A nonzero
child exit alone is not evidence of either limit. Each acceptance also requires
the owned process/cgroup observations and truthful cleanup disposition.

Existing model identity, historical replay refusal, finite reference admission
and the original scientific records remain unchanged. Consult
[model compatibility](model-compatibility.md) and the
[bounded assurance corpus](bounded-assurance.md) for those separate boundaries.
