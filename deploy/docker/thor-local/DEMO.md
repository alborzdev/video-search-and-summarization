# Thor VSS tradeshow runbook

This is the short operator path for demonstrating the fully local Thor
deployment. It assumes the connected bootstrap has already completed once.
Nothing in this runbook requires a cloud service.

## Before the doors open

After a host reboot, start the cache cleaner before the models and VSS stack:

```bash
pgrep -af /usr/local/bin/sys-cache-cleaner.sh || \
  sudo -b /usr/local/bin/sys-cache-cleaner.sh
cd /home/nvidia/cti-saa-thor/video-search-and-summarization/deploy/docker
./scripts/thor-local.sh status
./scripts/thor-local.sh doctor
```

The exact Nemotron 3 + Cosmos3 demo lane normally returns automatically through
its Docker restart policy. Generic `thor-local.sh up/restart` is intentionally
blocked while that lane is installed because it would replace its model and
consumer wiring. If `doctor` reports a failure after reboot, use the exact
**Verify identity** and **Render recovery** commands that it prints, run the
single pull-free command emitted by **Render recovery**, then rerun `doctor`.

Do not begin the demonstration unless `doctor` ends with zero failures. A
unified-memory warning is informational; close unrelated GPU or browser
workloads if available memory is approaching the documented capacity floor.
A disk-usage warning is acceptable only while at least 10 GiB remains free;
`doctor` fails below that hard floor.

Open the operator UI at `http://127.0.0.1:3001`. The supported public ingress
is `http://127.0.0.1:7777`; internal service ports are not customer-facing
interfaces.

Choose the customer vocabulary before the meeting:

```bash
./scripts/thor-local.sh domain list
./scripts/thor-local.sh domain show industrial-safety
./scripts/thor-local.sh domain apply industrial-safety
```

Applying a domain pack is offline-safe and restarts only the UI when its
branding changes. It prints the curated questions and searches for that pack.

## Ten-minute demonstration

1. **Ingest.** In **Video Management**, upload an MP4/MKV or register an RTSP
   URL. The status moves through ingestion and indexing before the source is
   ready for semantic search. Keep a pre-indexed video for a deterministic
   show-floor demo.
2. **Find an event.** In **Search**, enter a natural-language description. Open
   a result to play the exact matching time range and see detected objects.
3. **Find visually similar objects.** Pause a result, select a bounding box,
   then choose **Search by Image**. This uses the selected object's stored
   embedding as the seed; the similarity shown on each result is not an LLM
   guess.
4. **Ask the footage.** Use the VSS Agent panel to ask what videos exist, what
   happened in a named video, or for a concise summary. Answers are produced by
   the configured local OpenAI-compatible LLM/VLM providers.
5. **Show proactive verification.** Open **Alerts → Manage Alerts → Candidate
   Verification**. Explain that inexpensive video analytics proposes an event,
   then the VLM checks up to four ordered snapshots before an operator-visible
   alert is confirmed or rejected. This avoids running a large VLM on every
   frame.
6. **Investigate.** In **View Alerts**, expand an alert to show its evidence,
   VLM verdict, reason, snapshots, and clip. A rejected candidate remains
   auditable instead of being presented as a confirmed incident.
7. **Generate evidence.** Choose **Generate Report** on an alert. Open the
   Markdown or PDF result. Reports live in the private durable report store and
   remain available after the agent or full stack restarts.
8. **Close with operations.** Open **Dashboard → Thor VSS Overview** to show
   actual detected-object and behavior-event history. Finish with
   `./scripts/thor-local.sh doctor` to demonstrate that the entire product,
   models, media path, search path, and alert path are locally monitored.

## What each AI stage does

| Stage | Purpose | Runs continuously? |
| --- | --- | --- |
| DeepStream / RT-CV | Decode, detect, track, and create low-cost event candidates | Yes, for active streams |
| Cosmos Embed | Turn detected objects and temporal clips into vectors for semantic and visual similarity search | Yes, for indexed sources |
| Local VLM | Understand sampled frames, summarize video, and verify selected candidates | On demand / bounded chunks |
| Local LLM | Plan questions, combine evidence, and write summaries or reports | On demand |

The product is provider-agnostic at the LLM/VLM boundary, not capability-
agnostic. A replacement must expose the documented OpenAI-compatible contract.
Candidate verification and multi-frame video understanding require a vision
provider that accepts the configured number of images. An image-only endpoint
such as the current Moondream caption/query API can be integrated for
single-image tasks, but is not a drop-in replacement for the four-frame VLM
workflow.

## Show-floor safety and recovery

- Use only the loopback UI/ingress unless the host firewall and physical
  network were deliberately prepared for remote access.
- Never paste the NGC key into the UI, repository, Compose environment, or
  screenshots. Runtime containers receive blank registry credentials.
- Keep one known-good pre-indexed video. Live RTSP depends on the camera and
  venue network even though all inference remains local.
- If a model or service becomes unavailable, run `doctor`, inspect the named
  container with `docker logs --tail 150 <name>`, and follow the exact-model
  recovery commands printed by `doctor`. Do not use generic `restart` for the
  active exact-model lane, and do not run connected bootstrap on a show floor.
- Return to the neutral configuration after a customer-specific demo with
  `./scripts/thor-local.sh domain apply general`.

See [README.md](README.md) for bootstrap, storage, model, security, capacity,
and domain-pack details.
