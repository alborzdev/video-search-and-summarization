# Evidence

On 2026-08-10, target commit
`e96af9bbdc947e2c460ee34dec8ace129b1a86ab` passed the read-only Dashboard
runtime harness on Thor.

- VSS UI `vss-agent-ui:thor-local` was running from image ID
  `sha256:2b28982cf9a39017840132fb242766ff890c547a3abdb2f1e14de06818b3a594`.
- Kibana 9.3.3 was running and healthy from image ID
  `sha256:36301dc49650e47484b23803d60f78e0ac763ab4d7edab6c75c1f54a186d5f9d`.
- The UI selected the `Dashboard` control and rendered the embedded
  `thor-vss-overview` saved object titled `Thor VSS Overview`.
- Both required panels (`Detected Objects` and `Behavior Events`) rendered.
- Desktop 1440x900 and mobile 390x844 layouts passed; the mobile page had no
  horizontal overflow.
- Kibana's supported `xpack.security.showInsecureClusterWarning: false`
  setting kept the local demonstration dashboard free of the
  security upsell overlay at both viewports. This suppresses only that visual
  prompt; it does not add authentication or close the tracked firewall gap.
- The iframe used the exact dashboard path, embed hash prefix, title, and five
  sandbox tokens required by the fixture.
- A nonexistent adjacent dashboard ID returned HTTP 404.
- The run completed in 10.285 seconds using 7 browser actions, 4 direct API
  reads, and 336 loopback browser responses, within its declared bounds.
- No persistent resource or configuration was created, changed, or deleted.

The browser recorded three 404 calls to Kibana's disabled-security
`/internal/security/user_profile` path, three warnings, four console errors,
and two page errors. Every diagnostic matched the reviewed local-security
classification; there were no unknown 404 paths, no framework error overlay,
and the dashboard still rendered. This is retained as an open local-security
gap, not hidden or misreported as clean console output.

The complete machine-readable browser proof is `runtime-receipt.json`
(SHA-256
`800d5f9d0f821a4be971c3b63dc1be79d6fe9b37cfc8270627ba8404e0f5104a`).
`verify.py` validates its schema, exact contract/fixture/harness hashes, source
locks, target ancestry, bounds, and read-only postconditions offline. The
canonical capability proof is `official-runtime-evidence.json` (SHA-256
`436f55119607c83a1fbbf29cbd29d2fe18c40cfe1134d8f82bdb0370cd334e08`),
which is deterministically projected from that receipt and bound to the exact
Dashboard oracle without retaining raw page content or diagnostic text.
