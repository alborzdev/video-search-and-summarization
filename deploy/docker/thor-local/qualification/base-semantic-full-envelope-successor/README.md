# Base semantic full-envelope successor

This additive, Warehouse-free package combines the semantic request sequences
from `base-semantic-runtime-evidence` with the response-derived, exact-object
cleanup proven by `base-semantic-exact-cleanup-successor`. It does not rewrite
either predecessor or the selected Metadata-500 artifact.

The corrected successful envelopes are concrete and exact:

- Base chat/report: five reviewed semantic requests followed by two exact
  report reads, two exact deletes, and two individual 404 postconditions = 11;
- Base report HITL: six reviewed non-render semantic requests followed by the
  same six exact artifact operations = 12.

Each case source-locks one report-producing step: `generate-report` for Base
chat/report and `restart-and-check-persistence` for HITL. The manifest must
declare that step as nonempty SSE and require both `Markdown Report` and
`PDF Report`. The executor scans only that exact response for one same-stem
pair using the production `agent_report_*` / `vss_report_*` layout. A
valid-looking report link in any other semantic response is ignored and can
never acquire cleanup ownership.

Returned public report origins must be explicitly admitted by the manifest,
while every read and cleanup request is sent only to the selected
numeric-loopback Agent origin. The executor never treats `/static/<run-id>` as
a directory, requests recursive deletion, or derives a cleanup key outside the
case-pinned report response. A semantic or render assertion failure after pair
discovery still attempts both exact deletes and both exact 404 postconditions.

The default command is inert:

```bash
python3 deploy/docker/thor-local/qualification/base-semantic-full-envelope-successor/executor.py plan
```

After separately reviewing a closed manifest and confirming an already-running
local Agent, execution requires the exact acknowledgement:

```bash
python3 deploy/docker/thor-local/qualification/base-semantic-full-envelope-successor/executor.py \
  execute-http --manifest /absolute/reviewed.json --run-id RUN \
  --origin http://127.0.0.1:8000 \
  --acknowledgement I_ACK_BASE_FULL_ENVELOPE_LOCAL_RUNTIME
```

Proxies and redirects are disabled. Request/action, payload, response, and
timeout limits are enforced. Receipts contain hashes, sizes, status codes, and
fixed step identifiers—not raw request bodies, report contents, URLs, or
object keys.

## Deliberate evidence boundary

The selected Metadata-500 rows still have null executors, empty evidence, and
the frozen 8/11 planning envelopes. This package source-locks and audits that
state but does not bind itself into those rows. Its fake-only tests prove
control flow, bounds, exact cleanup, failure cleanup, admission, and receipt
validation; they are not Thor runtime evidence. A receipt from an authorized
live run would remain candidate evidence pending independent review and a
separate additive canonical binding/promotion decision.

The current generators use timestamp-derived upserts, so a future object-key
absence cannot be observed before generation. The receipt therefore records
`preexisting_absence_proven: false`; it proves exact removal of the finite pair
returned by the case-pinned report step and does not invent stronger pre-state
evidence.

Run mock-only tests with:

```bash
pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/base-semantic-full-envelope-successor/tests
```
