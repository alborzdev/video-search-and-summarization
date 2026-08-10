# Evidence

On 2026-08-10, target commit
`afef8a4a28291db768b1f1795758094302b70de7` passed the read-only Dashboard
runtime harness on Thor.

- VSS UI `vss-agent-ui:thor-local` was running from image ID
  `sha256:89988e7abf8bb22e9251dca84d188722629b549a8e9f0ece2a7bea03bbd94eb4`.
- Kibana 9.3.3 was running and healthy from image ID
  `sha256:36301dc49650e47484b23803d60f78e0ac763ab4d7edab6c75c1f54a186d5f9d`.
- The UI selected the `Dashboard` control and rendered the embedded
  `thor-vss-overview` saved object titled `Thor VSS Overview`.
- Both required panels (`Detected Objects` and `Behavior Events`) rendered.
- Desktop 1440x900 and mobile 390x844 layouts passed; the mobile page had no
  horizontal overflow.
- The iframe used the exact dashboard path, embed hash prefix, title, and five
  sandbox tokens required by the fixture.
- A nonexistent adjacent dashboard ID returned HTTP 404.
- The run completed in 9.406 seconds using 7 browser actions, 4 direct API
  reads, and 338 loopback browser responses, within its declared bounds.
- No persistent resource or configuration was created, changed, or deleted.

The browser recorded three 404 calls to Kibana's disabled-security
`/internal/security/user_profile` path, three warnings, four console errors,
and two page errors. Every diagnostic matched the reviewed local-security
classification; there were no unknown 404 paths, no framework error overlay,
and the dashboard still rendered. This is retained as an open local-security
gap, not hidden or misreported as clean console output.

The machine-readable proof is `runtime-receipt.json`; `verify.py` validates its
schema, exact contract/fixture/harness hashes, source locks, target ancestry,
bounds, and read-only postconditions offline.
