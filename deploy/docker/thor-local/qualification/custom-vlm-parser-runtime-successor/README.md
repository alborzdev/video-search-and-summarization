# Thor custom VLM parser runtime qualification

This package qualifies official capability row 326, `custom VLM parsing`,
against the current Thor-local VSS 3.2.1 runtime.

The harness starts an isolated Alert Bridge container from the exact active
Thor image on a loopback-only port. It bind-mounts the checked-in external
`ThorStructuredAlertParser`, configures its dotted class path, sends the small
checked-in warehouse warmup clip through the real on-demand REST API, invokes
the current local Cosmos Reason 3 RT-VLM, and verifies the acknowledged
Elasticsearch document. It also starts a second container with an invalid
parser path and proves startup fails before health becomes reachable.

The 100 GB warehouse bundle, external endpoints, and Agent `/generate` are not
used. All owned containers, indices, alert configuration, fixture serving, and
RT-VLM publications are removed before success is recorded; the primary VSS
runtime remains online and its exact projected state must match before/after.

Run the live qualification:

```bash
python3 harness.py \
  --acknowledgement I_AUTHORIZE_OWNED_CUSTOM_VLM_PARSER_QUALIFICATION \
  --run-id <unique-run-id> \
  --output runtime-receipt.json
```

Verify retained evidence without mutating runtime state:

```bash
python3 verify.py
```
