# Evidence

- Total planning requirements: **110**
- Integrated/materialized requirements: **26**
- Live-open requirements before and after this package: **84**
- Prior package selections through Wave 5: **44**
  - Currently materialized static bindings: **26**
  - Live-open candidate-only selections: **18**
- Exact previously unselected set audited: **66**
- New isolated static source-contract cases: **6**
- Source observations matching locked assertions: **6**
- Documented mismatch boundaries preserved: **5**
- External-optional boundaries preserved: **1**
- Requirements without a candidate executor afterward: **60**
- Runtime evidence added: **0**
- Live acceptance/oracle/manifest/lane/API changes: **0**
- Network, Docker, subprocess, lifecycle, credentials, or downloads: **0**
- Warehouse sample bundle used: **no**

## Exact set identities

```text
prior 44 package rows  3a6e3e23bb918167eb2359988416ec84baed1b8402f0b28103c96c28cf93560f
Wave 5 remainder 66    b51107200a0fd2e9c862c5576135c864ab1d9f041bf668dff2ff3934a5fe6f28
Wave 6 selected 6      ebed5e3724ad9935e7068974e51b3c7fcdd0506e78e10077a95afc5752d6fcc8
Wave 6 remainder 60    12bada9c389b5550910bfed7073281a59d63b5616266118e983f75522126c342
inventory raw SHA-256  bdcaf973fddf291fc35a0d27ae7a7a9414e5d62367c9100fef6d80f39d86fec7
```

The digests are canonical SHA-256 identities of sorted requirement-ID arrays,
except the inventory digest, which locks the exact checked-in bytes. The
executor also locks all seven baseline inputs—including the Wave 5 inventory—
and every source used by an assertion.

## Preserved boundaries

1. The official Smart City documentation states three different version
   identities; artifact locks do not make those statements consistent.
2. The official reference platform is x86 and excludes AGX Thor; this local
   profile remains a custom alternate.
3. The H100/L40S/RTX PRO 6000 stream table is reference-only and does not apply
   to Thor.
4. The official TrafficCamNet training recipe declares four classes while the
   checked local runtime surface documents five; VLM fine-tuning remains
   forthcoming.
5. The documented WebRTC, latency, long-run crash, and restart-recovery
   limitations remain active and must not be claimed remediated.

The CARLA/Cosmos Transfer case is separately retained as external-optional.
Existing local SDG tooling evidence does not turn it into a Smart City runtime
dependency or promote the still-open planning requirement.
