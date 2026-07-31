# Phase-1 RTVI file-lifecycle acceptance canary

Date: 2026-07-31

This milestone adds the first explicitly executable stateful acceptance slice
without changing the default inert planner. The only executable scenario is
`rtvi-file-lifecycle`: upload one deterministic client-addressed H.264 fixture
to RT-VLM and RT-Embed, verify metadata and downloaded bytes, then delete the
exact created IDs in strict reverse order.

Safety properties are enforced in code rather than left to operator convention:

- only numeric loopback origins are accepted; redirects and proxies are disabled;
- execution requires the scenario token and the current reviewed source fingerprint;
- a private append-only ledger records durable create intent before each mutation;
- ledger records form a validated hash chain and bind the canonical service-origin
  mapping through a separate execution fingerprint;
- uncertain creates remain cleanup candidates, interrupted cleanup resumes the
  exact top delete, and cleanup stops if that delete fails;
- evidence files are new, owner-only regular files and response bodies are bounded.

The fake-loopback suite covers successful lifecycle, pre-existing ID refusal,
lost/invalid/redirected/oversized create responses, cleanup failure and recovery,
interruption after `cleanup-started`, endpoint substitution refusal before
network access, and ledger tampering. The default plan reports zero network
requests and exposes no implicit execution switch.

Evidence collected:

- 27 Phase-0 unit tests passed;
- 9 Phase-1 fake-loopback test methods passed;
- the Thor stateful-acceptance wrapper passed;
- the broader 72-test Thor qualification suite passed.

No real VSS service was called and no container was started or stopped. This is
an executable acceptance mechanism, not current RT-VLM or RT-Embed runtime proof.
