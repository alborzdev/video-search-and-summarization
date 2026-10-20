# One application branch for Spark and Thor

Use `codex/unified-spark-thor` on both devices. It contains the entire
`codex/spark-tradeshow-offline` branch and all ten subsequent commits from
`codex/thor-tradeshow-port`, including the recording, recent-video question,
thumbnail, embedding publication and camera-discovery repairs. No cherry-picks
are needed: the Spark tip is an ancestor of the Thor tip. `thor-local` and
`agent/vss-3.2.1-thor-parity` are older checkpoints.

Keep application changes on this shared branch. Put device differences in
`tools/spark`, `tools/thor` and their deployment profiles. A change to a camera
question, search, recording or UI workflow belongs in the shared application
source. A change to a model image, GPU codec, startup sequence or memory budget
belongs in the relevant device profile. Both devices get the same features;
their supported inference runtimes remain hardware-specific.

## Clone and identify the device

```sh
git clone --branch codex/unified-spark-thor https://github.com/alborzdev/video-search-and-summarization.git
cd video-search-and-summarization
git lfs install --local
git lfs pull
python3 tools/runtime/platforms.py
python3 tools/runtime/bootstrap.py doctor
```

The common commands inspect the host's GPU and architecture on every invocation.
They refuse unsupported or ambiguous hardware. They do not choose a device from
shell variables, branch names or another machine's saved configuration.

## First installation

Read the device's setup instructions before downloading or starting workloads:

- **Spark:** [deployment and acceptance](spark-handoff.md),
  [desktop operation](spark-desktop-startup.md).
- **Thor:** [setup and staged startup](../tools/thor/README.md),
  [runtime qualification](../tools/runtime/README.md).

Both profiles support these common preparation commands:

```sh
python3 tools/runtime/bootstrap.py render --host-ip <device-IPv4>
python3 tools/runtime/bootstrap.py install-guard
```

Spark can use `127.0.0.1` for an on-device session. Use the actual Docker bridge
with `--gateway` when it differs from `172.17.0.1`. Preserve the saved data path
and memory reserve when rendering an existing installation. On Spark,
`--detector` enables the single-source detection/tracking worker.

Initial staging is device-specific. Spark uses `bootstrap.py stage`, then `up`;
Thor separately stages its pinned models and starts the support, model and app
stages described in its setup guide. The common bootstrap forwards arguments to
the selected profile; it does not equate these different staging sequences.
Initial installation needs at least 200 GiB free and private NVIDIA registry/model
credentials. Do not paste credentials into chat or commit them. Staging may take
considerably longer than a cached startup.

## Daily operation after installation

These commands are the same on both devices:

```sh
python3 tools/runtime/desktop.py check --no-open
python3 tools/runtime/desktop.py start --no-open
python3 tools/runtime/ui.py deps
python3 tools/runtime/ui.py dev
python3 tools/runtime/ui.py status
python3 tools/runtime/bootstrap.py stop
```

`check` verifies local offline assets. `start` uses the selected device's
launcher and guard. Omit `--no-open` to open the app in the device's configured
browser. UI `deps` is an explicit online setup step; reuse installed dependencies
for ordinary source edits. Keep the saved reserve and model budgets intact.
On a fresh Spark without a registered local simulator, startup opens the app for
recorded clips. Add the RTSP source later; no simulator is required for file use.
Existing local Sim installations retain their recording/indexing startup path,
and unrelated cameras are never migrated or activated as a simulator.
For Spark's full recording/analysis shutdown, use
`python3 tools/runtime/desktop.py stop --no-open`; Thor currently exposes its
service stop through the common bootstrap. See the device guides for details.

## Update both devices

On each device, preserve local changes, then fetch and fast-forward the shared
branch. Stop VSS before changing deployment scripts or packaged backend source.
Application source, not recordings or model caches, is synchronized by Git.

```sh
git switch codex/unified-spark-thor
git pull --ff-only
git lfs pull
python3 tools/runtime/bootstrap.py doctor
```

For UI edits, use the [source-mounted development workflow](ui-development.md).
For backend or deployment changes, follow the affected profile's render,
build/stage and guarded restart procedure. Pulling source alone does not rebuild
an existing image. Validate on the actual target; Spark tests cannot establish
Thor runtime acceptance.

Keep `.spark/`, `.thor/`, credentials, recordings, databases and TensorRT engines
local to each device. Never copy generated device settings or compiled engines
between Spark and Thor. Keep the existing branches as recovery checkpoints until
the shared branch has been exercised on both machines.
