# Thor-local Qwen alternate qualifier

This package provides one bounded runtime check for the already-provisioned
`datasheet-chat` and `datasheet-vision` endpoints. It is deliberately a
**non-official local alternate** lane. A pass does not establish official NVIDIA
model equivalence, does not advance an official VSS capability, and must not be
copied into the acceptance inventory or capability oracles as official runtime
evidence.

The contract binds:

- VSS 3.2.1 at peeled tag commit
  `7640d917047cf7b0fd3085eefb8282754b56bc94`;
- reviewed upstream `main`
  `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`;
- the local source baseline
  `ee82896c01e66e03502d24bdafe6b46e20679785`;
- the actual commit current when evidence is emitted, resolved read-only from
  `.git/HEAD` without Git or another subprocess;
- the complete artifact lock SHA-256 and the canonical lock entries for
  `Qwen/Qwen3.6-35B-A3B-FP8` at revision `95a723d...` and
  `Qwen/Qwen3-VL-8B-Instruct-FP8` at revision `9cdc631...`;
- vLLM image digest `sha256:6402d5ac...`;
- exact local endpoint/model pairs: `172.17.0.1:8000` / `datasheet-chat` and
  `172.17.0.1:8003` / `datasheet-vision`.

## Inert plan mode

The default mode validates the checked contract and artifact ledger, prints a
JSON plan to stdout, and sends no HTTP requests:

```bash
python3 deploy/docker/thor-local/qualification/local-alternate-models/qualify.py
```

It never calls Docker or a subprocess, reads credentials, downloads anything,
changes lifecycle state, or writes a file.

## Explicit bounded execution

Execution requires the exact acknowledgement below. Do not run it until the
operator has separately started both endpoints and authorized runtime probing.

```bash
python3 deploy/docker/thor-local/qualification/local-alternate-models/qualify.py \
  --execute \
  --ack I_ACKNOWLEDGE_THIS_IS_A_NON_OFFICIAL_ALTERNATE_MODEL_TEST_WITH_NO_OFFICIAL_VSS_CAPABILITY_PROMOTION
```

The execute path makes at most four direct, no-proxy HTTP requests, in order:

1. exact `/v1/models` identity at the LLM endpoint;
2. exact `/v1/models` identity at the VLM endpoint;
3. one forced `ping` tool-call request with
   `chat_template_kwargs.enable_thinking=false`;
4. one four-image vision request using deterministic 56×56 red, green, blue, and
   yellow PNGs generated only in memory.

Every request has a ten-second transport timeout, a 256 KiB request limit, and
a 1 MiB response limit. Redirects are rejected and never followed. The client
uses fixed IPv4 hosts directly and does not consult proxy variables. Requests
carry no credentials. Output is controlled JSON evidence on stdout; raw model
responses are never printed or retained.

The evidence document validates against `evidence.schema.json`. A `passed`
document proves only that this exact alternate pair satisfied these four probes
at that moment. It does not prove container-image identity by introspection—the
digest is the required deployment binding—and it performs no deployment or
cleanup itself.
