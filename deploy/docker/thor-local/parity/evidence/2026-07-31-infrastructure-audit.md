# Thor infrastructure audit — 2026-07-31

The resolved unified Thor profile already selects Kafka, Redis,
Elasticsearch, Logstash, Kibana, and Phoenix, with exact ARM64 application
images protected by the Thor image lock. Historical Phoenix logs contain
successful agent `POST /phoenix/v1/traces` requests, but that is prior evidence
and not a current trace roundtrip.

The source milestone in `2026-07-31-observability-wiring.md` adds a bounded,
loopback-only Thor selection for Prometheus, Grafana, node-exporter, and
cAdvisor. Its profile-specific scrape configuration includes only
source-proven, selected targets. All four exact ARM64 monitoring images are now
staged and pass the source/image contract, but the profile remains unstarted
and therefore not runtime-qualified. NVIDIA's
DCGM exporter is intentionally excluded until it proves useful on Jetson AGX
Thor; a local `tegrastats` exporter is the fallback if DCGM cannot report the
integrated GPU.

Additional open infrastructure gaps found by the audit:

- RT-Embed, RT-VLM, RT-CV, and LVS OpenTelemetry exporters are disabled in the
  unified profile and no collector is selected. Phoenix trace ingest must be
  qualified separately from Prometheus scraping.
- Phoenix has no functional healthcheck and publishes unauthenticated port
  6006 on all interfaces; current listener/firewall evidence remains required.
- Thor now resolves Logstash to an ARM64 derivative built from a checked-in
  expected digest and an official offline pack with build networking disabled.
  Clean startup and Kafka protobuf-to-Elasticsearch ingestion are still
  unqualified.
- The two broker consumers now fix `KafkaError._PARTITION_EOF`, use bounded
  deterministic capture controls, decode source-proven topics, and commit/ack
  only after flushed output. Their mocked suite passes; finite live Kafka and
  Redis captures remain open.
- Prometheus/Grafana/Phoenix and the remaining core infrastructure need current
  healthchecks, current target/trace/dashboard evidence, and a pull-free forced
  recreation before this family can pass.

No container lifecycle, image download, port exposure, or host-permission
change was performed during this audit.
