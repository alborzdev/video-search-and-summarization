# Thor VSS tradeshow runbook

This is the short operator path for demonstrating the fully local Thor
deployment. It assumes the connected bootstrap has already completed once.
Nothing in this runbook requires a cloud service.

## Before the doors open

After a host reboot, keep the periodic cache cleaner and the VSS graph stopped:

```bash
cd /home/nvidia/cti-saa-thor/video-search-and-summarization/deploy/docker
./scripts/thor-local.sh stop
./scripts/thor-local.sh status
./scripts/thor-local.sh doctor
```

The exact Nemotron 3 + Cosmos3 co-resident graph produced two whole-host stalls
on this 128 GiB Thor and was reset by the 120-second hardware watchdog. It is
therefore safety-locked. `thor_demo.py audit` now requires a conservative 64 GiB
post-load reserve; it must remain `BLOCKED` on this host. The periodic
three-second `sync`/`drop_caches` loop is also rejected for this lane.

Use a split local-model deployment or a remote endpoint for one model before
running this demonstration. Do not bypass the audit or replay an older rendered
Compose command. Every model and GPU-capable service remains `restart: "no"` so
a reboot returns to a stable stopped state without deleting data. Agent startup
also leaves registered live sources inactive; an explicit operator resume is
required after a future replacement topology passes acceptance.

Do not begin the demonstration unless `doctor` ends with zero failures. A
unified-memory warning is informational; close unrelated GPU or browser
workloads if available memory is approaching the documented capacity floor.
A disk-usage warning is acceptable only while at least 10 GiB remains free;
`doctor` fails below that hard floor.

Only after a split/remote topology is implemented and accepted, open
`http://10.88.8.175:7777` on Thor or another device on the approved local
network. While the safety lock is active, the gateway and port 3001 may both be
unavailable because the graph is intentionally stopped.

Choose the customer vocabulary before the meeting:

```bash
./scripts/thor-local.sh domain list
./scripts/thor-local.sh domain show industrial-safety
./scripts/thor-local.sh domain apply industrial-safety
```

Applying a domain pack is offline-safe and restarts only the UI when its
branding changes. It prints the curated questions and searches for that pack.

## Ten-minute demonstration

1. **Ingest.** In **Manage → Sources**, upload an MP4/MKV or register an RTSP
   URL. The status moves through ingestion and indexing before the source is
   ready for semantic search. Keep a pre-indexed video for a deterministic
   show-floor demo.
2. **Find an event.** In **Investigate**, enter a natural-language description. Open
   a result to play the exact matching time range and see detected objects.
3. **Build an evidence set.** Select useful ranked results with **Use as
   evidence**, then summarize the selected set. Search-by-image remains
   conditional on tracked-object IDs and frame boxes; do not present it when
   the current source provides only clip embeddings.
4. **Ask the footage.** Use **Operations → Vision Analyst** to ask what videos exist, what
   happened in a named video, or for a concise summary. Answers are produced by
   the configured local OpenAI-compatible LLM/VLM providers.
5. **Show proactive verification.** Open **Manage → Alert rules → Candidate
   Verification**. Explain that inexpensive video analytics proposes an event,
   then the VLM checks up to four ordered snapshots before an operator-visible
   alert is confirmed or rejected. This avoids running a large VLM on every
   frame.
6. **Investigate.** In **Operations → Activity**, open an incident to show its evidence,
   VLM verdict, reason, snapshots, and clip. A rejected candidate remains
   auditable instead of being presented as a confirmed incident.
7. **Generate evidence.** Choose **Generate Report** on an alert. Open the
   Markdown or PDF result. Reports live in the private durable report store and
   remain available after the agent or full stack restarts.
8. **Close with operations.** Open **Operations → Insights** to show
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

- Use the LAN gateway only on a deliberately prepared, trusted simulator or
  tradeshow network. It has no login or TLS boundary; never port-forward it to
  the internet or expose internal service ports.
- Never paste the NGC key into the UI, repository, Compose environment, or
  screenshots. Runtime containers receive blank registry credentials.
- Keep one known-good pre-indexed video. Live RTSP depends on the camera and
  venue network even though all inference remains local.
- If a model or service becomes unavailable, run `doctor` and inspect the named
  container with `docker logs --tail 150 <name>`. While the exact co-resident
  lane is safety-locked, `doctor` intentionally provides containment—not a
  recovery command. Do not use generic `restart`, and do not run connected
  bootstrap on a show floor.
- Return to the neutral configuration after a customer-specific demo with
  `./scripts/thor-local.sh domain apply general`.

See [README.md](README.md) for bootstrap, storage, model, security, capacity,
and domain-pack details.

The CTAILabs workflow and acceptance evidence are recorded in
[`../../../docs/vision-intelligence-operator-guide.md`](../../../docs/vision-intelligence-operator-guide.md),
[`../../../docs/vision-intelligence-parity.md`](../../../docs/vision-intelligence-parity.md),
and
[`../../../docs/vision-intelligence-acceptance.md`](../../../docs/vision-intelligence-acceptance.md).
