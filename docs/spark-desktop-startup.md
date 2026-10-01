# Starting VSS at the booth

The Desktop has **Start VSS** (green play icon) and **Stop VSS** (red stop icon).
Both are also available in the Applications menu. They use the images, models,
engines and app dependencies already stored on this Spark; startup does not
download or install anything and does not ask for credentials or sudo.

## Open the session

1. Start the simulator with its existing **Start CTaiLABS Demo** shortcut. Wait
   until the intended scene is visible and its RTSP stream is publishing.
2. Double-click **Start VSS**. Leave the progress window open while the models
   warm up. Allow **10–15 minutes from a cold start**; prepare before visitors
   arrive. A repeated start with healthy services is much faster.
3. Chromium opens [Video workflow](http://127.0.0.1:7777/?workspace=guided) in
   a new tab, using the same browser session as the simulator shortcut.
   Check the actual scene, **Live preview**, **Search indexing active**, and
   advancing searchable coverage before presenting. Fresh recording, indexing,
   detection and tracking are restored automatically.
4. Follow **Watch → Ask → Find → Follow → Monitor → Review** using the
   [booth playbook](demo-presenter-runbook.md).

Visual monitoring rules start paused after a cold start, leaving the visual
model available for questions. Activate a rule explicitly in the app when you
reach Monitor, then pause it before asking another visual question. Clicking
Start VSS again while services are healthy preserves existing monitoring settings.

If the simulator is not publishing yet, VSS stays open and tells you to start
the Sim and click Start VSS again. The app uses a fixed local address, independent
of venue Wi-Fi, DHCP or Internet access. Old bookmarks using `10.88.9.91:7777`
should be replaced with the local link above. This setup is for the browser on
the Spark; access from other computers is not configured by these shortcuts.

If the publisher comes online after camera discovery, Start VSS verifies recent
recorded footage (or probes the local RTSP video path if capture is off) and
recovers the stale discovery status before restoring
indexing and tracking. This restarts only the CPU camera discovery service;
the recorder, simulator and loaded models keep running. Questions use verified
recent recordings, so a delayed discovery status does not block available video.
An old discovery flag can also say online after the publisher exits. The launcher
now requires a successful local RTSP video probe before starting capture or
analysis. If the Sim is absent, it leaves VSS available and asks you to start the
Sim and click Start VSS again. A missing publisher does not qualify as ready.

The registered camera still has its historical **Spark Hospital Corridor** name.
Check the footage when switching the simulator to the warehouse. The launcher
preserves the camera identity and does not relabel earlier evidence.

## End the session

Double-click **Stop VSS** and wait for its completion message before powering
off the Spark. It pauses monitoring and analysis, ends live capture and stops
the VSS services. Saved recordings, reports, rules and cached models remain.
The simulator stays under its own shortcut's control.

Stop VSS can also interrupt a startup. Multiple simultaneous starts are refused
with a clear message. Nothing starts VSS or Moondream automatically on login.
The existing 24 GiB memory reserve and memory guard remain active.

## If startup reports a problem

Use the log path shown in the error dialog and ask the technical lead. Do not
present the system as ready until fresh indexed footage has been verified. A
failed startup that brought services up stops the partial VSS stack; it preserves
data and leaves the simulator alone. Retrying Start VSS on a healthy, loaded
session preserves the models and monitoring settings if a later app or source
check fails. Camera discovery retries temporary errors during recovery.

The app refreshes the camera catalog automatically, including when it was empty
at boot. Event review keeps records from a healthy analytics service visible if
the other service is recovering, and labels incomplete coverage. A detector rule
can resume only when the selected source still supports its object types. Each
source supports one active proximity rule; pause it before enabling another.

Immediately after a reboot, Start VSS gives Docker up to 45 seconds to become
available instead of failing on its first connection attempt. A partial model
session is shut down gracefully before a cold retry so startup admission uses
the correct memory headroom. Failed/dead containers are reported promptly,
initialization jobs follow their dependency definitions, and cleanup failures
do not replace the original startup error in the log.

Camera health updates preserve the selected camera, question draft and workflow
chapter. A briefly empty background catalog retains known cameras with unknown
connection health and a restoration warning. **Connected** now requires live
video frames; a saved poster or stale discovery state cannot claim a live feed.

Cold startup clears stale visual-alert ownership for the Sim source, including
orphaned files left by a bridge restart. Pausing an already missing backend job
releases its ownership, so it cannot keep blocking questions. Resume verifies
the actual job: a healthy job is preserved, a missing job is recreated, and a
failed/stopped job asks you to pause it before resuming. Temporary backend errors
remain errors rather than being treated as missing jobs.

Failed live previews also retry when the publisher reconnects or the browser
returns from the background. Camera switches cancel obsolete preview requests.
Visual questions have a bounded queue: up to three requests may wait, with a
30-second queue deadline. If the model is still busy, the app returns a retry
message instead of leaving old questions queued indefinitely.

The launcher applies bounded Docker file logging to the cached service graph
without changing model settings. Existing file log limits are preserved; missing
limits default to three 20 MB files per container. These limits take effect when
the affected containers are recreated during the next cold Start VSS. A warm
start preserves loaded models. The memory guard continues protecting the reserve
after Docker errors and retries failed stops during an ongoing low-memory period.

## Full-day operation

The October 1 second audit passed 106 scoped regression checks, including
accelerated eight-hour track churn and reconnect scenarios, plus the app
typecheck, offline cache preflight and a real three-second warehouse question.
The Kafka source patch is mounted into both CPU analytics workers; both resumed
processing fresh frames after their reload. The simulator, recorder and all three
model containers stayed running, with the 24 GiB reserve unchanged.

A five-minute observation of the current single warehouse camera recorded
307 MB of additional video. Its measured rate projects to about 29 GB of video
and 33 GB total disk growth over eight hours; about 1.27 TB remained free.
Available memory stayed between 36.6 and 36.8 GiB and searchable coverage advanced
at every sample. These figures describe this camera and workload, not capacity
for additional cameras or heavy concurrent inspections.

This is not an actual eight-hour disconnected rehearsal. Such a rehearsal is
still needed with the intended simulator activity, questions and monitoring.
Analytics health alone does not prove event processing: check fresh indexed
coverage and a real rule event. Current Kafka processing also lacks durable
acknowledgement after a completed analytics batch, so detector events during a
worker outage are not guaranteed to be replayed automatically. Recording is
separate and remains available for inspection.

The further fresh-boot triage verified the unavailable-publisher launcher branch
against the running app without starting/stopping services. At that checkpoint
the simulator was no longer listening on RTSP port 8554, while its discovery flag
still said online; the app correctly displayed **Live video unavailable** and
the launcher returned the start-the-Sim instruction. The local asset audit found
no automatic external script/style/image dependencies in the tested workspace.
Fresh-boot timing, missing-job recovery and camera health transitions also have
isolated regression coverage; this does not substitute for a physical offline
reboot rehearsal.

For technical checks, from this checkout:

```sh
python3 tools/spark/desktop.py check --no-open
python3 tools/spark/desktop.py start --no-open
python3 tools/spark/desktop.py stop --no-open
```

`check` verifies local images, pinned model shards, compiled GB10 engines, the
pinned Kafka parser, the pinned video decoder wheel, data folders and app dependencies.
It installs that decoder in a fresh CPU-only agent container and verifies video
decoding with Docker networking disabled. It does not launch models, change recording, or fetch
missing assets. Restore missing assets before going offline. Logs are private
files under `.spark/desktop-logs/`.

The Kafka parser is cached in `.spark/offline-tools/jq` and mounted read-only
even when its initialization container is recreated. Offline startup never
downloads this tool. Logstash uses a local bootstrap that loads its shared
protobuf path and core dependency before starting its two pipelines.

The agent's OpenCV/FFmpeg wheel is also cached in `.spark/offline-tools/`, verified
against the exact SHA256 in `services/agent/uv.lock`, and mounted read-only.
Container recreation uses this local wheel, with network retries disabled.
Missing or changed decoder assets fail preflight before any models start.
The explicit online technical staging command (`bootstrap.py stage`) restores
this asset; the desktop shortcut never downloads it. Do not remove the wheel.

The October 1 reboot exposed two additional startup bugs: the agent's optional
decoder installer had been reaching PyPI despite cached model weights, and
pausing saved caption history failed when the new runtime had no caption job.
The first is now checked with a fresh network-isolated agent image; the second
accepts only the exact missing-resource response after a successful inventory
confirms that source is absent. Other caption-control failures still surface.
Startup now also verifies playable recent footage before announcing readiness,
and reports exhausted container health checks without waiting another hour.

Reinstall the shortcuts if needed with:

```sh
python3 tools/spark/desktop.py install
```

The launcher keeps the current source-mounted app so the latest workspace is
shown. Do not delete its checkout, `services/ui/node_modules`, `.spark/`, Docker
images or model/data volumes before the show. This is a local prototype launcher,
not a portable installer. See the [verification receipt](qa/2026-10-01-spark-desktop-launcher.md)
for tested scope and remaining rehearsal checks.


The current launcher also starts the CPU-only history maintenance service and a loopback-only, read-only recording metadata helper. Both use cached tools, and neither starts at login. **Stop VSS** stops them along with VSS; the simulator stays independent. The **Clear history** control is available in the top bar and System. It clears a confirmed history snapshot without stopping the source, changing rules, downloading models or changing the memory reserve.
