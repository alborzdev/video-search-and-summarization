# Thor AutoMagicCalib runtime qualification — 2026-08-09

## Result

The standalone VSS 3.2.1 AutoMagicCalib backend and UI ran locally on AGX Thor
without the excluded Warehouse sample bundle. The official small four-camera
fixture completed base AMC with the fixed ResNet detector.

- Project: `20260809_190004_6638`
- Final state: `project_state=COMPLETED`, `amc_state=COMPLETED`
- Runtime: 1,640 seconds (27m20s)
- Inputs: four ordered MP4 cameras, alignment JSON, layout PNG, and `GT.zip`
- Fixture lock: 160,499,115 bytes,
  SHA-256 `0dceb0cc8324f5775b0c2007efe7a3e7c36fda10c5964b88e20712b002d98bdb`
- Backend image ID/repository digest:
  `sha256:6ed911d45d500424301c4de74ca68aa66d9e88a6efc1ddd06dca8b40fb536982`
- UI image ID:
  `sha256:e86c16ac9e88241dabd35e6f44c2d5086a77551a3e3654b4905e51bbf4cdf6a4`

The readiness endpoint and UI both returned HTTP 200. Project creation, four
video uploads, alignment upload, layout upload, ground-truth upload, project
verification, calibration start, status polling, evaluation retrieval, overlay
retrieval, project listing, and MV3DT export all succeeded through the live
REST API.

## Accuracy and outputs

The ground-truth evaluator returned:

- average L2 distance: 0.11 m;
- L2 standard deviation: 0.05 m;
- maximum L2 distance: 0.29 m;
- average reprojection error 0: 1.62 px;
- reprojection-error-0 standard deviation: 1.18 px;
- maximum reprojection error 0: 9.03 px; and
- average reprojection error 1: 1.80 px.

All base-AMC acceptance thresholds passed. Three local overlay images were
produced with SHA-256 values:

- `overlay_img_00.png`:
  `18440ae955e50adf3bcf7f9b93692569a5f84e3e15e5f19690d39b633ce3a49c`
- `overlay_img_01.png`:
  `68d7f223b72e1bdd50fa060b8cf5353cce713931547e08c115e7bb3aaccae8b2`
- `overlay_img_02.png`:
  `264edd02a9cede8f544b29388c3273119942cead2b595b2390cd63b6f9f98919`

`GET /v1/result/{project_id}/overlay_image` returned HTTP 200 PNG, 879x1308,
whose SHA-256 matched `overlay_img_02.png`. The AMC MV3DT endpoint returned
HTTP 200 ZIP with SHA-256
`5bdb81dde4028f9c54ae68ad0f04745e72b9737580687ae836ecbc76c45a5e7e`.
Its seven-member contract contained `map.png`, `transforms.yml`, and four
camera-info YAML files. The calibration log SHA-256 was
`46086a3ecf7bd7d33044e64de72530c4dee4d24b39e8deebf4c5e9305dea3a26`.

Generated project media and results remain in the host bind mount and are
intentionally Git-ignored. This evidence retains identifiers and hashes rather
than committing videos or generated binary output.

## Reboot, resource isolation, and persistence

The first attempt was interrupted by a hard host reboot while camera 0 was at
150/500 background-extraction frames. `last -x` classified the prior boot as a
crash; no persistent previous-boot journal was available, so no kernel, power,
or OOM cause can be asserted. The incomplete project files survived in the
host bind mount, but the API state entry did not: NVIDIA's state manager saves
`projects/state.json` only during graceful application shutdown.

After reboot, Docker retained the required `cgroupfs` driver. Postgres, Redis,
Kafka, Phoenix, VIOS Sensor/Stream Processing, Video Analytics API, RT-CV, and
Alert Bridge were restored and returned to their expected running/healthy
states.

The full inference stack had 114,150/125,772 MB RAM in use, only about 10 GiB
available, no swap, and six 4 MB largest-free blocks before the replacement
run. Five competing VSS inference containers were temporarily stopped by exact
ID: Nemotron Edge, RT-VLM, RT-Embed, RT-CV, and LVS. Available memory rose to
30 GiB and largest-free blocks rose to 287x4 MB. The replacement run enforced
12 GiB memory and disk safety floors, never approached either floor, and
completed without a restart. Host polling retained at least roughly 25 GiB
available memory throughout the run.

After completion, a graceful backend restart wrote a 1,258-byte
`projects/state.json`, reloaded exactly one project, and returned the same
`COMPLETED` project through the API. This proves the documented graceful
persistence path. It does not claim recovery of in-flight work after a hard
host crash.

## Hardened deployment and API contract

The two upstream profile containers were then recreated through the checked-in
Thor overlay. The backend and UI used the immutable image identities recorded
above, automatic restart was disabled, and local logs were bounded. The backend
process listened on `127.0.0.1:8010`; the UI publication listened on
`127.0.0.1:5000` and advertised `http://127.0.0.1:8010/v1` as its API. The
completed project reloaded after this recreation and remained `COMPLETED` with
four video files and base-AMC results available.

The pull-free inventory check, official-fixture verifier, and GET-only runtime
qualifier all passed. Live qualification covered readiness, UI HTTP 200, VIOS
sensor-list reachability, and all 26 skill-advertised API operations. The live
service publishes its OpenAPI document at root `/openapi.yaml` and represents
the concrete `/v1/amc/calibrate/{project_id}/log` request as the parameterized
schema path `/v1/{type}/calibrate/{project_id}/log`; the Thor qualifier and its
regression tests now match that exact NVIDIA contract.

## Post-qualification profile recovery

All five inference containers paused for calibration were restored and reached
their service health gates: exact-model Cosmos3 RT-VLM, Nemotron 3 Nano 4B FP8,
RT-Embed, LVS, and RT-CV. RT-VLM initially rejected startup because only 30.6
GiB was free while its exact 0.35 vLLM allocation requires 42.99 GiB at process
admission. Starting Cosmos3 before the other inference services resolved the
ordering constraint. The upstream single-node Kafka broker also reserved a
fixed 6 GiB JVM heap; the Thor overlay now uses an overridable 1 GiB heap. The
broker remained healthy with all 22 existing topics and about 0.9-1.2 GiB
resident usage. A controlled RT-VLM restart then initialized its Kafka producer,
loaded all four model shards, and returned healthy with zero automatic restarts.

The official Thor demo verifier passed its exact image, artifact, model,
environment, mount, endpoint, and Agent readiness contract. Two local consumers
had inherited the literal placeholder `local` in `OPENAI_API_KEY`; no operator
credential was present. The official-edge overlay now forces standard
credential variables empty for LVS and VA-MCP even when Compose is invoked
directly, and all 46 official-edge unit tests passed before isolated recreation
of those two healthy services.

Running AutoMagicCalib, observability collectors, and every inference lane at
the same time left less than 5 GiB available unified memory with no swap. After
proving their live contracts, AutoMagicCalib, its UI, the dashboard collectors,
and idle/no-stream RT-CV were placed in a safe stopped state. RT-CV had already
reached healthy and reported no active DeepStream stream; its bounded stop
needed Docker's timeout kill but owned no mutable stream session. The remaining
core local model, Agent, search, summarization, embedding, broker, analytics,
and alert services retained roughly 11 GiB available memory. These optional
lanes remain installed and are intended to be started on demand rather than
left co-resident unattended.

## Optional VGGT boundary

Base AMC does not require VGGT. The separately licensed
`vggt_1B_commercial.pt` checkpoint is absent, and backend startup reported
`VGGT available: False`. VGGT refinement was not invoked and remains an
explicit licensed-artifact boundary rather than a base-AMC failure.
