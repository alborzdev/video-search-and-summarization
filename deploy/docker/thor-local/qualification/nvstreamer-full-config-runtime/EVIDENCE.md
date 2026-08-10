# Evidence

Status: passed current on Thor (`2026-08-10`).

The bounded loopback-only runtime transaction passed against the exact offline
arm64 image `vss-vios-nvstreamer:3.2.1-thor-local` (image ID
`sha256:b3e5b92fa2546e9b69a3dba7cac324ce36a3cce65f2e0d61ad41a8a84a74a563`,
service `streamer` version `2.1.0-26.05.4`). It established:

- official VSS 3.2.1 table: 151 parameters across `network`, `onvif`, `data`,
  `notifications`, `debug`, `overlay`, and `security`;
- current parser coverage: 151/151 documented keys;
- NVIDIA's shipped Docker Compose NvStreamer JSON carries 148/151 keys;
- the derived Thor fixture explicitly adds the three parser-supported omissions:
  `enable_aging_policy`, `use_centralize_local_db`, and
  `update_record_details_in_sec`;
- five live configuration APIs returned HTTP 200 with 41 sensor, 20 storage,
  51 live, 48 replay, and 31 proxy fields;
- 21 representative values spanning every documented section matched the
  mounted configuration;
- a writable `stunUrlList` value changed, read back, restored, and read back
  exactly, with all four operations returning HTTP 200;
- all 10 HTTP responses succeeded and all 12 startup configuration markers
  were present;
- all external notification, authentication, and telemetry effects remained
  disabled and all HTTP/RTSP exposure was bound to loopback;
- the exact pre-test Docker inventory and running set were restored and all
  reserved ports were released.

Retained immutable artifacts:

- `runtime-receipt.json`:
  `53363105ec52afada6f12238be7b80f0037d678ccec806829c47014119ce07a8`;
- `official-runtime-evidence.json`:
  `59aa9c7c46bb8ea49398e20a7a9d109597b4115fbd33cb843a9d11bccee695e7`;
- `fixture-contract.json`:
  `7eb3789fcb182afe4259fd4c00e80d29ddbf68d929e648a2f06bac19b34db3b9`;
- `execute.py`:
  `5b76bb4d6580c697271703239317de6526fa6157731ef2fc3a202eccdf3e82ff`;
- bound capability oracle:
  `c1433eab90e0d997983b9cb5a292f79f4e6a71115fca182a8b68fa696886fd7a`.

The transaction downloaded and installed nothing, used no warehouse sample,
did not modify the main VIOS or RT-CV deployments, and did not call the gated
VSS Agent generation endpoint.
