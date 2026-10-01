# Spark recovery, September 30, 2026

The Spark guard stopped the VSS Compose stack at about 23:17 EDT when available
memory reached 23.795 GiB, below the configured 24 GiB reserve. The exact workload
responsible for the drop is not established by the available guard snapshot.
The app, agent and detector reported OOMKilled=false. Host uptime was unchanged.
The guard stop receipt is preserved in guard-trip.json.

Recovered with tools/spark/bootstrap.py up, retaining the 24 GiB reserve and
existing model budgets. All startup health probes passed. Restored the source UI
with tools/spark/ui.py dev; app HTTP 200 and Video workflow rendered in the Codex
browser. Source analysis was partial after restart; explicit Pause analysis then
Resume analysis reconciled detection, embedding and indexing to active.

Browser verified fresh coverage at 23:42:02 EDT and 6,347 indexed intervals,
advancing beyond the pre-shutdown 6,342 count and 23:17 timestamp. Local AI reported
online. Available memory after recovery was about 36 GiB. This is a recovery
checkpoint, not a sustained workload qualification or a diagnosis of the initial
memory growth. The existing source retains its hospital name and scene.
