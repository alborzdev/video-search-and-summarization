# Evidence

The retained receipt is admission-grade evidence for official rows 324 and 325. Two direct operator-triggered `/api/v1/verification/ondemand` requests use independent configured category mappings; one is submitted through a case-normalized alias. Both return server-generated job identifiers, advance through observable states to deterministic `completed` / `verified` / `confirmed` verdicts, retain reasoning plus `OK` parse status, and produce acknowledged local Elasticsearch documents correlated to distinct mapped output categories.

The same bounded run proves that a third independently admitted job can be cancelled before publication and remains `cancelled` with no Alert Bridge sink document after the settle window. An unknown category is rejected with HTTP 400 before any job ID is allocated. The fixture server, both owned configs, exact owned sink documents, and uniquely tagged RT-VLM backend publications are removed, while pre-existing configs, incidents, realtime rules, RT-VLM streams, and running containers have identical canonical before/after digests.

The run also verifies the Thor fixes that inline private/loopback media before local VLM inference and normalize Elasticsearch `ObjectApiResponse.body` into an acknowledged sink receipt. It makes zero Agent `/generate` calls and uses no external endpoint or warehouse sample data.
