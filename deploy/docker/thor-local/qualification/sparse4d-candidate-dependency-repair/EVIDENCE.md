# Sparse4D candidate dependency repair evidence

Date: 2026-08-02
Scope: static repository evidence only

## Decision

GO for the additive planning repair. NO-GO for an in-place edit of the selected
Metadata-500 set: the live-ready descriptor, selector activation receipt, and
later executable-subset evidence raw-lock those existing bytes.

## Exact identities

- selected candidate/oracle index: `457`;
- manifest pointer: `/features/26/advertised/0`;
- candidate oracle canonical SHA-256:
  `45ef0ea3e789ce812c8d6345b43e9637caca3e17bee7ba50a90fcada811d0a19`;
- candidate capability before SHA-256:
  `8e20dee77f1cc2049ef892a05d086a8a4581c9b04b3d3996eca1d768ac04d7cf`;
- single-field corrected capability SHA-256:
  `086e0cadd433638f890d86d9c1bf95ec0ecab037fb3c4c52323f7b0ff12afd90`;
- wrong MV3DT capability/oracle SHA-256:
  `6f4c15a07410953a524ba5ed92974f66e68ca72a89caf9bd412a1719dee22679` /
  `cfb536bf724b54a16c12a164df8f6e92975b7e46d68eca2ac149b790481191c6`;
- correct Sparse4D capability/oracle SHA-256:
  `da47b32625aa4c75378a3e1afa8f8c95b276a78da6bf45caab0f57b965451939` /
  `9881c395728e8540f49c94157b8d2313ba6895c160da38319e6dafaf77c289ce`;
- predecessor mapping raw SHA-256:
  `4bb8f3a5fba5e201b72e1f1a0f4218bff4b9a999a836c192fca44ca7e35d9cf9`;
- repair payload/raw SHA-256:
  `ef308921bd58ce44243692a46438d365cc4998cb733b877684d6bf1944deb84b` /
  `2ed1a2bb1afc7b3e79d4a1a688d770780639f307f06f29d222e13f3d23683ffd`.

## Objective mismatch

The affected record is Sparse4D in all four independent dimensions: advertised
literal, source Compose surface, required observations, and adjacent-negative
case. The locked wrong dependency is MV3DT in all of its distinguishing
runtime dimensions: RT-DETR detector, MV3DT tracker, and MQTT inter-camera
broker. The selected correct dependency declares Sparse4D perception,
`mdx-bev`, and synchronized camera timestamps.

The source Compose independently identifies `perception-3d` extending
`perception`, container `vss-rtvi-cv`, and the Sparse4D ONNX/anchor. The Thor
overlay and launcher independently retain `MODE=3d`, `bp_wh_redis_3d`, offline
model behavior, and `DS_MODEL_FAMILY=sparse4d-warehouse`.

## Claim boundary

The repair proves only dependency and approval-scope classification. It creates
zero approvals, receipts, runtime actions, evidence records, promotions, or
metadata mutations. It does not prove model presence, input availability,
service health, inference, fused tracks, cleanup, or runtime qualification.
No network, Docker, service, model, host, or Warehouse sample action was used.
