# Deploy — Data directory layout

### Step 1b — Prepare the data directory

**This is the #1 source of silent-deploy bugs. Follow it exactly.**

The stack mounts several subdirs of `$VSS_DATA_DIR` into containers that each
run as a different uid. Docker auto-creates empty bind-mount paths as
`root:root`, which is read-only for the container processes.

The deployment helper provisions only missing directories with a shared
setgid group. Existing service-owned paths and files are deliberately left
unchanged. Prefer `dev-profile.sh up`, which applies this safely. For a manual
Compose workflow, use the equivalent non-recursive preparation below:

```bash
DATA=$VSS_DATA_DIR      # e.g. <repo>/data
install -d -m 2770 -g "${VSS_DATA_GID:-1000}" \
  "$DATA/data_log/analytics_cache" \
  "$DATA/data_log/calibration_toolkit" \
  "$DATA/data_log/elastic/data" \
  "$DATA/data_log/elastic/logs" \
  "$DATA/data_log/kafka" \
  "$DATA/data_log/redis/data" \
  "$DATA/data_log/redis/log" \
  "$DATA/agent_eval/dataset" \
  "$DATA/agent_eval/results"
# Profile-specific paths should use the same install command and mode:
#   alerts → data_log/vss_video_analytics_api, videos/dev-profile-alerts,
#            models/rtdetr-its, models/gdino
#   search → models
```

> **FORBIDDEN: recursive `chown` or `chmod 777` under `$VSS_DATA_DIR`.**
>
> The services intentionally own persisted children under different UIDs.
> Recursively replacing ownership or granting world-write access can both
> break that contract and expose video/model data. Set group access only when
> a directory is first created; do not rewrite existing persisted contents.

**If postgres is already broken** (common when redeploying without a clean
`data-dir`):

```bash
docker logs vss-vios-postgres
# Resolve the actual volume (its name is <compose_project>_vios_pg_data — the
# project prefix varies by deploy, so detect it rather than hard-coding it):
vol=$(docker volume ls --format '{{.Name}}' | grep 'vios_pg_data$')
# If the logs show a corrupted/stale PGDATA volume, stop the stack, then:
docker volume rm "$vol"
```
