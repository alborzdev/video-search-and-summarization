# LVS recommended configuration runtime qualification

This package proves official row 303 against the deployed Thor LVS service.
It source-locks the released NVIDIA VSS 3.2.1 implementation and live OpenAPI,
calls `POST /recommended_config`, verifies request and response bounds, then
submits the returned `chunk_size` unchanged as `chunk_duration` in one real
local Cosmos `/generate_vlm_captions` request.

The released API recommends `chunk_size` and returns explanatory `text`. It
does not expose frame, token, or model-context recommendation fields. The
generated 500-row ledger overstates that contract, so this package records the
discrepancy and qualifies the authoritative released behavior rather than
inventing incompatible fields.

The harness uploads one owned checked-in H.264 fixture and restores the exact
LVS file catalog, Neo4j counts, LVS runtime state, and running-container set.

```bash
python3 deploy/docker/thor-local/qualification/lvs-recommended-config-runtime-successor/harness.py \
  --ack I_ACK_ONE_OWNED_LVS_FILE_AND_ONE_RECOMMENDED_CONFIG_FOLLOW_ON
python3 deploy/docker/thor-local/qualification/lvs-recommended-config-runtime-successor/verify.py
python3 -m pytest -q \
  deploy/docker/thor-local/qualification/lvs-recommended-config-runtime-successor/tests/test_package.py
```
