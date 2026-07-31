# Thor Smart City profile

This overlay runs NVIDIA VSS Smart City analytics for the single
`Agnew_head_on` sample camera while reusing the Thor-full Kafka, Elasticsearch,
VIOS, analytics API, agent, UI, alert, search, and summarization services. It
does not start the upstream Google Maps UI or query OpenStreetMap at runtime.

The checked-in calibration, road-network JSON, and GraphML are deterministic
derivatives of NVIDIA's multi-camera sample. Regenerate or verify them with:

```bash
python3 deploy/docker/developer-profiles/dev-profile-thor-smartcity/scripts/derive-smartcity-assets.py
python3 deploy/docker/developer-profiles/dev-profile-thor-smartcity/scripts/derive-smartcity-assets.py --check
```

Select the profile through the Thor-local driver:

```bash
THOR_LOCAL_COMPOSE_PROFILES=bp_developer_thor_full_2d,bp_developer_thor_smartcity_2d \
  deploy/docker/scripts/thor-local.sh refresh-runtime
THOR_LOCAL_COMPOSE_PROFILES=bp_developer_thor_full_2d,bp_developer_thor_smartcity_2d \
  deploy/docker/scripts/thor-local.sh up
```

The Smart City profile replaces only RT-CV and adds a uniquely grouped
behavior consumer, a bounded calibration importer, and a local static map. The
map is available through the supported ingress at
`http://127.0.0.1:7777/smartcity-map/` and inside the VSS UI Map tab. It renders
the official road geometry as local SVG, uses bundled JSON when the analytics
API is not ready, and makes no browser requests to a map or font provider.

Do not combine `bp_developer_thor_smartcity_2d` with
`bp_developer_thor_search_perception_2d`: both deliberately claim the one Thor
GPU, RT-CV health port 9000, and container name `vss-rtvi-cv`.

Run the static contract test without starting containers:

```bash
bash deploy/docker/test-scripts/test-thor-smartcity-profile.sh
```
