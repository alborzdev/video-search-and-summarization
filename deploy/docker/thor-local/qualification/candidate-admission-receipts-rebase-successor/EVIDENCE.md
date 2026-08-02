# Candidate admission receipts rebase evidence

The compiler raw-locks 18 finalized sources: mapping-v2 and runtime-bundle artifact/schema/compiler/tests; the rebased 500-oracle artifact/schema; and migration plus activation artifact/schema/compiler/tests. It validates every JSON/schema pair and proves the activation receipt binds the exact migration proof while both retain zero runtime evidence and zero promotable candidates.

Separate immutable locks protect all eight historical admission-package files plus the canonical selector and staged descriptor. Historical comparison strips only six per-row provenance hashes, then requires all 211 remaining row objects, the policy, summary, and ordered bundle IDs to match exactly.

Checked outputs:

- `admission-index.json`: `74398a4239cfd13f753924aaf65b5ce16e6f96b44dc9eae8067eddb8a03456ff`
- `admission-index.schema.json`: `54cef2f2dc7879f817ff21c2b2472b19629d23c028fc25c3cee04fe9f09926d7`
- canonical admission rows: `57c583cad3ffc86d87a673d92c54f68fd765867eb1cf08839393d7a2ad3a4ef0`
- `receipt-set.json`: `e3d3d918bb392d903c00d82687efbf24d7c834019761929304019bbd4930132f`
- `receipt-set.schema.json`: `63dfd032bb3625fd1d5002f19a10e25f72f1c775c9f2c5ce6ee1121531449c10`

These artifacts prove only a deterministic fail-closed admission boundary: 211 dispositions, zero receipts, zero trusted authorities, zero admissions, and zero executable candidates. They do not authorize or execute any runtime, network, Docker, host, firewall, model, download, or Warehouse activity.
