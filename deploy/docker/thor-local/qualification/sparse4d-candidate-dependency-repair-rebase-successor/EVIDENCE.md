# Sparse4D repair rebase evidence

Date: 2026-08-02
Scope: static checked repository evidence only

## Decision

GO for the additive planning rebase successor. NO-GO for runtime execution,
approval, admission, evidence promotion, or mutation of historical/canonical
metadata.

## Rebase identities

- mapping rebase: `dd5be5e9a73245c3599309497b8b3d9e68c750656984fb0f166423730956722a`;
- mapping schema: `41271a9716e1462d789e9e26a98f9d4a49a830157be4d9c0105ea9824bebc3d5`;
- projected selector: `d44bb521d56f87e32396b619b70ee0b2c645e79bc6d78ebd8c6a380575f25112`;
- projected descriptor: `4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca`;
- migration receipt: `771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c`;
- migration-rebase ledger/oracles: `8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13` /
  `911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021`;
- final protocol artifact/schema: `cea6cf41109654fa040f120c74a17b253c019b38cfb1a1e8229d370c2f10d5f7` /
  `399471d0efd73614e507426095390a4a2e731aa4970b916199344b89b0304fbb`.

## Preserved semantic identities

- historical repair raw/payload: `2ed1a2bb1afc7b3e79d4a1a688d770780639f307f06f29d222e13f3d23683ffd` /
  `ef308921bd58ce44243692a46438d365cc4998cb733b877684d6bf1944deb84b`;
- candidate before/after: `8e20dee77f1cc2049ef892a05d086a8a4581c9b04b3d3996eca1d768ac04d7cf` /
  `086e0cadd433638f890d86d9c1bf95ec0ecab037fb3c4c52323f7b0ff12afd90`;
- candidate oracle: `45ef0ea3e789ce812c8d6345b43e9637caca3e17bee7ba50a90fcada811d0a19`;
- correct Sparse4D capability/oracle: `da47b32625aa4c75378a3e1afa8f8c95b276a78da6bf45caab0f57b965451939` /
  `9881c395728e8540f49c94157b8d2313ba6895c160da38319e6dafaf77c289ce`;
- wrong MV3DT capability/oracle: `6f4c15a07410953a524ba5ed92974f66e68ca72a89caf9bd412a1719dee22679` /
  `cfb536bf724b54a16c12a164df8f6e92975b7e46d68eca2ac149b790481191c6`.

The successor artifact payload/raw identities are
`8d16d8c768d947d878802d7b9f8259444e6398d81211358011ec0fc547633ca5` /
`099b89d6e0b75b01e768b71ebaa6b0a719153185cf7aba5e6d0e5eb50e3247d7`.

## Non-evidence

No runtime, service, network, Docker, model, host, Warehouse sample, approval,
admission, receipt, or promotion action occurred. Candidate evidence remains
empty, executor readiness remains false, runtime state remains `not_qualified`,
and the operator-approval gate remains unmet.
