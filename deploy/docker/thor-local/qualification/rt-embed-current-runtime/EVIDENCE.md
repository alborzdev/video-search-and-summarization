# RT-Embed retained runtime evidence

The bounded Thor run passed in 89.791 seconds with 43 total HTTP requests, 41
privacy-safe retained observations, and four semantic actions. It matched the
live 22-path OpenAPI document and exercised every one of the 24 documented
`/v1` operations, including local RTSP registration, live SSE generation,
inference stop, single deletion, and batch deletion.

The exact locked `nvidia/Cosmos-Embed1-448p-anomaly-detection` revision
`3b1455ed97c7b1d5419c0c3129b7199ca4cd9382` passed. The verifier read the
4,793,036,482-byte model tree and 9,661,728,403-byte generated fp16 Triton tree
from the existing named volumes. The artifact lock records the two generated
`config.pbtxt` files with their actual `0664` mode; their bytes, sizes, and all
other tree entries remain exactly locked.

Two text inputs produced finite 768-dimensional vectors. The tracked H.264
fixture produced three finite chunks through upload and three through an RFC
2397 data URL; ranges, dimensions, and vector hashes were identical, with
pairwise cosine 1.0. A real local RTSP stream produced a finite
768-dimensional SSE chunk. Duplicate camera registration returned transport
HTTP 409 with `DuplicateCameraId`; duplicate batch-stream registration retained
the documented outer HTTP 200 and nested 409 `DuplicateStreamId` result.

The unset `FILE_URL_ALLOWED_DIRS` branch rejected `file://` input with HTTP 403
and created no asset. Positive narrow-directory and traversal cases remain a
separate unqualified capability.

After execution, complete file and both stream inventories, asset statistics,
RT-Embed image/start/health/restart/OOM/mount/environment identity, and the
three operator-paused workloads matched pre-state exactly. All six fixed UUIDs,
the fixed camera, publisher, RTSP path, and three helpers were absent. No image
pull, build, model staging, external request, service lifecycle action, VIOS
mutation, VSS Agent call, or Warehouse sample use occurred.

- Contract SHA-256: `ff00f1cb91045a9f758c3dc23223fc6bc562b9a1819735e8c97d790c96ca2494`
- Receipt SHA-256: `56da7bf867628791152cdb9c3cdf788801ab77aa3e4dedb374ba130bf9849934`
- Model evidence SHA-256: `38e367d7d35e18d7e80cf9b0a20ec324e68750e2767a4ce3f0abf289e35dbe99`
- Data-URL evidence SHA-256: `f9cd87923a4d66c2f89641bd52a70f3cbfb1b950f6c0725960415d0d0d6beeb6`
- Duplicate-ID evidence SHA-256: `4fd5ce16811e73041b935398b49729d0499dcdd20c8adb49ea3f03878b855b89`
- API evidence SHA-256: `033cdb49311c8b5c443aaa5f921d682c5c03a3abd0147d6e278e2c6043497586`
- Model oracle SHA-256: `3454e6b38fe07cedc0c7ad161eb08454577aae0c72768b5ede6f21731674a5b8`
- Data-URL oracle SHA-256: `e0daf993d9f121b25e4d7b7154da2fb24599cf029dcdded4c45c48c156461530`
- Duplicate-ID oracle SHA-256: `264f74135902bd5d5d8a7841d92c01aa96d8a0224fc482dd5da197525066a12b`
- API oracle SHA-256: `5eec9567bca3543a1452215ad88becfc53ea00aaf03ec45fc647affebbadf66a`
