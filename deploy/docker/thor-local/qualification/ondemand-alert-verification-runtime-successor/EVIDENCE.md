# Evidence

The retained receipt is admission-grade evidence for official row 325 only. It proves a direct operator-triggered `/api/v1/verification/ondemand` request returned a server-generated job identifier, advanced through observable states to a deterministic `completed` / `verified` / `confirmed` verdict, and produced an acknowledged local Elasticsearch document correlated to the exact event, sensor, mapped category, reasoning, and response status.

The same bounded run proves that a second independently admitted job can be cancelled before publication and remains `cancelled` with no Alert Bridge sink document after the settle window. An unknown category is rejected with HTTP 400 before any job ID is allocated. The fixture server, owned config, exact owned sink document, and uniquely tagged RT-VLM backend publications are removed, while pre-existing configs, incidents, realtime rules, RT-VLM streams, and running containers have identical canonical before/after digests.

The run also verifies the Thor fixes that inline private/loopback media before local VLM inference and normalize Elasticsearch `ObjectApiResponse.body` into an acknowledged sink receipt. It makes zero Agent `/generate` calls and uses no external endpoint or warehouse sample data.
