# SpatialAI Runtime Evidence

The authoritative integrated receipt records a clean Thor checkout at
`f7ea82feef81739b6861f49e8a2eb5fea9583900` with tree
`d86ca3a4bffdc99c0693a135f5b3623f8b98edce`, based on VSS 3.2.1 upstream
commit `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`.

The seven ordered provider-free SpatialAI capabilities each passed two
independent positive runs and five adjacent-negative cases. In total the
receipt records 49 bounded actions, 49 requests, 122 imported product-function
calls, 14 positive runs, and 35 rejected adjacent negatives. Output was
deterministic and cleanup was exact.

The confinement record has zero network, Docker, service-lifecycle, model,
download, Warehouse-sample, product-subprocess, and filesystem-escape activity.
The AWS/GCS entry `07` was not touched.

Authority bindings:

- Integrated receipt SHA-256: `9ca6de79ac42605a80b5de9c2397ba4d303fdc423e9713a061a520f3a730fce7`
- Extracted producer receipt SHA-256: `9c0c9294b78bc5e01b8cc9500a70f050bb52d7b618399a13569b78064966d95a`
- Producer contract SHA-256: `029b17846f5e137d6aaad1e092abd444e7e17f112517841ce59fc960b096ec70`
- Producer executor SHA-256: `6f3af563886565f2688f97472fa2e6d993f8dc47ed12215d2d02c77ac4f8066c`

The canonical oracle rows remain `open_unexecuted` with empty oracle evidence;
their readiness is `executor_ready`. Runtime qualification is recorded in the
ledger through the separately reviewed aggregate receipt. The aggregate family
remains `partial/not_qualified` because external optional entry `07` remains an
unexecuted provider boundary.
