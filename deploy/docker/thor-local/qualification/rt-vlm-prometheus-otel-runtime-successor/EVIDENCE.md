# Evidence

The retained Thor run passed in 0.695769 seconds with zero model requests. The
live `/v1/metrics` endpoint exposed fourteen metric families with exact RT-VLM
3.2.1 OpenTelemetry resource labels. The pinned local Prometheus target was up,
had no scrape error, used the exact bridge URL, and returned one `up=1` series.

An isolated process imported the production `otel_helper`, initialized the
supported console trace and metric exporters, recorded and flushed one span and
one counter, and retained only boolean assertions plus a digest of its output.
RT-VLM and Prometheus remained healthy with zero restarts and no OOM events.

No trace/span identifiers, credentials, prompts, assets, streams, Warehouse
sample data, VSS Agent calls, or service lifecycle actions are retained.
