# Thor infrastructure audit — 2026-07-31

The resolved unified Thor profile already selects Kafka, Redis,
Elasticsearch, Logstash, Kibana, and Phoenix, with exact ARM64 application
images protected by the Thor image lock. Historical Phoenix logs contain
successful agent `POST /phoenix/v1/traces` requests, but that is prior evidence
and not a current trace roundtrip.

The source milestone in `2026-07-31-observability-wiring.md` adds a bounded,
loopback-only Thor selection for Prometheus, Grafana, node-exporter, and
cAdvisor, and a local tegrastats exporter. Its profile-specific scrape
configuration includes only source-proven, selected targets. All four exact
ARM64 monitoring images are now staged; tegrastats reuses the locked VSS Agent
image and host L4T binary, so it needs no fifth image. Static source/image
contracts pass, but the profile remains unstarted and therefore not
runtime-qualified. NVIDIA's DCGM exporter remains excluded on Jetson AGX Thor;
the bounded tegrastats exporter is the selected integrated-GPU temperature,
power, and system telemetry path.

Additional open infrastructure gaps found by the audit:

- RT-Embed, RT-VLM, RT-CV, and LVS OpenTelemetry exporters are disabled in the
  unified profile and no collector is selected. Phoenix trace ingest must be
  qualified separately from Prometheus scraping.
- Thor binds the direct Phoenix and Logstash management APIs to loopback.
  Phoenix now joins the host network with inherited bridge ports removed, has
  a database-backed `/readyz` healthcheck, disables its default telemetry
  pixels and external UI resources, and is reached by both the agent and
  host-mode HAProxy through the same `127.0.0.1`. Non-Thor HAProxy profiles
  preserve their prior `HOST_IP` default. Kibana retains its host binding for the
  bridged UI's `host.docker.internal` server-side discovery path; its port is
  now explicitly included in the Thor firewall/listener audit, while its usage
  telemetry, OpenTelemetry export, newsfeed, and Fleet registry access are
  disabled in the shared air-gapped VSS config.
- Thor now resolves Logstash to an ARM64 derivative built from a checked-in
  expected digest and an official offline pack with build networking disabled.
  Clean startup and Kafka protobuf-to-Elasticsearch ingestion are still
  unqualified.
- The two broker consumers now fix `KafkaError._PARTITION_EOF`, use bounded
  deterministic capture controls, decode source-proven topics, and commit/ack
  only after flushed output. Their mocked suite passes; finite live Kafka and
  Redis captures remain open.
- Prometheus/Grafana/Phoenix and the remaining core infrastructure need current
  live health, target/trace/dashboard evidence, and a pull-free forced
  recreation before this family can pass. The read-only runtime tier now
  encodes all three endpoints plus an exact seven-job Prometheus target gate.

No container lifecycle, image download, port exposure, or host-permission
change was performed during this audit.
