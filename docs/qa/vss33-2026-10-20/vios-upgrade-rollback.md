# VIOS 3.2.1 → source-fixed 3.3 upgrade and rollback review

Read-only source/SQL review on October 21. Compared current compiled source with custom `c4a44c4d956a8c039483f8f392544b8f999dc62c`; no database, media, saved report, generated appliance configuration, or container lifecycle changes were made by this audit. The separate explicitly authorized renderer cap edit changes source only.

## Decision

No destructive schema migration is present. The main PostgreSQL17.9 database can receive the additive migration while retaining the 3.2.1 sensor process. Treat first activation as a bounded two-existing-file-source playback test, not RTSP qualification. Preserve a database dump **and matching filesystem/config snapshot** first: temporary URL expiry and the existing recording aging policy are active code paths, so an image-only rollback is not a complete data rollback.

### Every startup schema difference

`src/framework/database/postgresql/postgresql_helper.cpp:createDatabaseTables` is invoked by `Postgresql::getInstance()` on its first connection (header lines53–59). Compared with c4a, the only new schema changes are:

- `ALTER TABLE TEMP_VIDEO_FILES ADD COLUMN IF NOT EXISTS CONFIG_HASH VARCHAR(64) DEFAULT '';` The column is nullable; existing rows obtain the empty default. Fresh table creation includes the same column.
- New ordinary btree `idx_temp_files_stream_time_v2(device_id,stream_id,start_time_ms,end_time_ms,file_type,config_hash)`. The existing five-column `idx_temp_files_stream_time` is retained. It is not renamed or dropped, and the new index is not unique.
- The four older idempotent `ADD COLUMN` operations for `start_time_ms`, `end_time_ms`, `file_type`, `container_format` and expiry/device indexes remain; all four columns and older indexes were confirmed present in the actual main database before activation.
- The eleven existing table declarations, sensor/stream uniqueness/FKs and media columns are unchanged. There is no startup DROP, TRUNCATE, type conversion, schema reset, or recording-row rewrite in this diff. `VST_DB_VERSION` remains `"0"`; this version value cannot distinguish the new column from old schema.
- Existing startup writes remain: set DB version, attempt initial admin-user insertion (duplicate unique username is rejected), preserve existing device ID and synchronize configured device name/location. The main database already has one local-device row. Do not remove it or change selected data mounts: its ID ties shared sensor/stream state together.

Source references: `postgresql_helper.cpp:3934–4006`, `postgresql_helper.cpp:4010–4028`, `database_schema.h:241`, `framework/apis/common/device_manager.cpp:591–667`.

### Old-binary compatibility

The old source uses explicit column lists for temp-file inserts/selects, maps result fields by names, and ignores unknown fields. It therefore tolerates the extra nullable/defaulted column and extra non-unique index. The retained old sensor process does not require the new column. This is source-supported compatibility, not a live old-binary/new-schema rehearsal.

Cache behavior differs: 3.3 partitions URL caches by overlay/transcode/resize configuration using `config_hash` and refreshes container/hash on a file-path conflict. An old binary's cache lookup has no hash predicate. If 3.3 generated multiple transformed variants for the same stream/time, image-only rollback can reuse the wrong cached variant. A lossless rollback should restore the original `temp_video_files` rows and matching physical temp entries with the full pre-upgrade snapshot, rather than blanket-delete the cache. Do not manually drop the new column/index to roll back.

### Startup file mutation and cleanup

- `TempFileScheduler::initializeFromDatabase` immediately cleans expired video/image temp records and schedules unexpired ones; storage, live and replay modules initialize these schedulers. This behavior is unchanged from c4a. Callbacks unlink the recorded temp pathname and delete its DB row; full-file passthrough is a symlink, so normal expiry unlinks the symlink rather than its backing clip. A bad legacy temp row could still point elsewhere: the baseline should inspect `file_path` privately and confirm every tracked row is under `webroot/temp_files` before activation.
- Recording aging remains enabled through environment, with 100000MB quota, 95% threshold and a two-second polling interval. It may delete oldest media/DB rows (and, for a FILE source whose final recording is removed, its stream/sensor details) if storage thresholds are crossed. The periodic code is unchanged from c4a. Do not reduce retention, change quotas, invoke DELETE/aging APIs, or run disk cleanup during upgrade.
- Crash-recovery code can update zero-duration recording rows when enabled. The source `MODULE=streamprocessing` build does not define `MONOLITH_MODULE`; absent `ENABLE_RECORDING_RECOVERY`, recovery remains disabled. The two actual main recording rows have nonzero duration and size.
- Startup notifies existing online FILE sensors (`camera_add`, `camera_proxy`, `camera_streaming`) using their existing IDs. It does not import arbitrary local files. Cloud import is gated by disabled cloud-storage settings. Keep Agent source desired states paused and avoid actions that start analysis/recording.
- New DASH creates output only when a viewer starts. Its stop/idle reaper removes the exact generated token subdirectory under its configured DASH root; the safety check requires the expected parent and token filename. Rolling pruning only removes generated segment files. This does not target `vst_video`, `streamer_videos`, `temp_files`, or PG rows. Default output root `dash` lives under the streamprocessor's webroot; it is disposable derived media, not the original archive. Stop viewers before replacement and expect previous DASH URLs to expire.
- The new failed-upload cleanup removes its partial transcode output only on that failed request; it is not a startup media sweep. Explicit delete/time-delete paths retain old semantics, with extra reversed-range validation and the already-custom FILE multi-stream cleanup. No delete endpoint is required for this rollout.
- New overlay asset startup downloads are conditional on nonempty calibration/floor-map endpoints. They atomically replace only the configured asset and its `.download.tmp`, retaining an existing valid asset on failure. Current selected configuration has empty endpoints; no main media rewrite is expected. Preserve the config mount regardless.
- Saved reports/history/rules are outside VIOS mounts (`agent-reports`, `vision-history`, `vision-investigations`, `vision-rules`) and are not referenced by any native VIOS cleanup. Back them up privately as an independent preservation check, but never restore those live user stores to an older snapshot merely to revert VIOS.

Source references: `utilities/TempFileScheduler.cpp:77–124`; `storage_management.cpp:140–153,505–629,4333–4465`; `streamrecorder.cpp:209–309`; `media/video_source/senders/dash_packager_consumer.cpp:684–710`; `media/dash/dash_session_manager.cpp:1618–1765`; `storage_management_utils.cpp:2024–2044`; `utilities/config.cpp:1521–1637`.

### Mixed old sensor / new stream processor contracts

No required breaking wire field was found. Proxy add/remove routes and JSON event names remain `camera_proxy`/`camera_remove` with `event.camera_id`, `camera_url`, `camera_name`, `change`, optional tags/metadata. New stream processor still accepts these old fields; missing optional metadata defaults empty. Sensor/stream PostgreSQL columns and type strings (`sensor_file`, RTSP/ONVIF types) remain compatible. New stream JSON only adds optional `tags`; no enum renumbering was found in the reviewed sensor declarations.

The newer source sensor module fixes direct REST-vs-SDRC selection, but this upgrade deliberately retains the old3.2.1 sensor image. It does not acquire that source fix. Existing old sensor + retained SDR forwarding remains the topology; no new behavior or live-camera claim follows from the streamprocessor swap. Actual main DB currently has only two `sensor_file` entries and no camera URL was provided. Existing archive IDs must be retained. RTSP add/remove/resume needs its own later bounded test with the user's actual source.

## Pre-upgrade qualification boundary

The read-only main-appliance check found two existing uploaded FILE sources, two
stream and recording rows, one temporary video-cache row, one local-device row,
and no active recording-status/schedule rows. Both media records had nonzero
size/duration. The original cache migration columns and indexes were present;
`config_hash` was absent. Refresh these counts, exact IDs, paths, symlink targets,
and file hashes in the private backup immediately before activation. Do not
publish the private row-level baseline or database dump.

The isolated encoded playback receipt used a fresh PostgreSQL17.9 namespace initialized by VIOS3.3. It
does not establish preservation of this appliance's existing3.2 state. Existing
archive identity/media/report comparisons are required after main activation.
There is no user-provided RTSP source and no new live-ingestion qualification.

## Concrete root-run backup and validation plan

The commands below are a reviewed procedure, **not executed by this audit**. Keep the guard/reserve, ACT, inference model budgets and all unrelated services unchanged. Hold UI uploads/deletes/rules and automatic source resume; drain viewers and confirm no recording/ingest writer. Stop/recreate only the selected streamprocessor for the eventual image change. If other VIOS writers are active, quiesce them explicitly before capturing the paired snapshot; a concurrent PG dump and media copy is not an atomic application backup.

```sh
umask 077
vios_backup="/home/sparkdev/vss/work/vss33/vios-before-native-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$vios_backup"
# Capture immutable identities; never print full environment or database rows with credentials.
docker inspect --format '{{.Image}}' vss-vios-streamprocessing > "$vios_backup/old-streamprocessor-image-id.txt"
docker inspect --format '{{.Image}}' vss-vios-sensor > "$vios_backup/old-sensor-image-id.txt"
docker image inspect --format '{{.Id}}' vss-vios-streamprocessing:3.3-native > "$vios_backup/new-streamprocessor-image-id.txt"
cp -p .spark/settings.json .spark/compose.json .spark/generated.env .spark/vst-config.json "$vios_backup/"
# Logical PG dump: do not copy a live PostgreSQL data volume with tar.
docker exec vss-vios-postgres pg_dump --username=vst --dbname=nvcentralizedb --format=custom --no-owner --no-acl --serializable-deferrable --lock-wait-timeout=15s > "$vios_backup/nvcentralizedb.dump"
test -s "$vios_backup/nvcentralizedb.dump"
docker exec -i vss-vios-postgres pg_restore --list < "$vios_backup/nvcentralizedb.dump" > "$vios_backup/dump-toc.txt"
docker exec -i vss-vios-postgres psql -X -v ON_ERROR_STOP=1 -U vst -d nvcentralizedb -At < docs/qa/vss33-2026-10-20/vios-baseline.sql > "$vios_backup/db-before.jsonl"
# tar preserves symlinks instead of dereferencing uploaded-file cache links.
# Skip only the live PostgreSQL socket and its lock in the shared socket directory.
tar --acls --xattrs --numeric-owner --exclude='vst_data/.s.PGSQL.*' -C /home/sparkdev/vss/.spark/data/data_log/vst -cpf "$vios_backup/vios-media.tar" vst_data vst_video clip_storage temp_files
# Preserve independent saved content too; no VIOS rollback should replace it.
tar --acls --xattrs --numeric-owner -C /home/sparkdev/vss/.spark/data -cpf "$vios_backup/saved-content.tar" agent-reports vision-history vision-investigations vision-rules
sha256sum "$vios_backup"/*.dump "$vios_backup"/*.tar > "$vios_backup/checksums.sha256"
docker exec -i vss-vios-postgres pg_restore --list < "$vios_backup/nvcentralizedb.dump" > /dev/null
```

Use the full private dump as recovery evidence: it contains private sensor credentials and session/password hashes even though the separate JSON baseline deliberately omits them. Keep the directory700/files600 and do not paste dump/schema-data contents into logs. Record a sorted lstat manifest and SHA256 of every regular media/report file, plus raw symlink targets (without following them), at the quiesced point. Preserve UID/GID/mode/mtime. In particular, compare actual `video_record_details.file_path` values with the mounts, and ensure the `temp_files` symlink target is an existing clip under `clip_storage`.

For stronger backup verification, root may restore the dump into a uniquely named empty disposable database (`createdb --template=template0`) on the same17.9 cluster, using `pg_restore --exit-on-error --single-transaction --no-owner --no-acl -U vst -d <disposable_db>`, run the baseline there and compare table counts/IDs/sequences. Do not point any application at that database. Listing a dump TOC alone verifies readable structure, not a complete successful restore. Dispose of only that exact test database after evidence is saved.

After selection and single-role recreation, run the same read-only SQL baseline. Expected: all original sensor/stream/recording IDs and file hashes unchanged; only nullable config_hash and the new index added, plus legitimate derived temp-cache entries/expiry. Confirm old sensor image ID unchanged. Read-only archive playback on an original source UUID from the private baseline should not create a new source. UI reports and their playable evidence must still open. Review all unexpected count changes before any RTSP work.

## Rollback root-run procedure

1. Freeze mutations/viewers, stop only the new streamprocessor, preserve a post-failure PG dump and media/config manifest. If full DB restoration is necessary, prevent old sensor/SDR/other VIOS writers for that maintenance window; leave PG17.9 and unrelated ACT/model services running.
2. Revert renderer selection with explicit empty string and preserve the recorded old image ID. Restoring `.spark/compose.json`/settings/vst-config from the private backup is also possible when it does not undo independent later configuration work. Do not change PG major version, recreate/prune its volume, reset device IDs, or run `compose down -v`.
3. An image-only fallback is structurally supported by additive columns, but does not restore expired files/cache keys. For exact pre-upgrade state, root can run (only after explicit writers are quiesced and post-state evidence preserved):

```sh
# DESTRUCTIVE RESTORE OF THIS ONE DATABASE; root must select the verified backup.
docker exec -i vss-vios-postgres pg_restore --exit-on-error --clean --if-exists --single-transaction --no-owner --no-acl -U vst -d nvcentralizedb < "$vios_backup/nvcentralizedb.dump"
# Restore media/config from the SAME snapshot. First extract to a separate review
# directory; compare paths/ownership/symlinks, then copy only reviewed restored
# entries into the existing mounts. Do not broadly delete current directories.
```

`pg_restore --clean` drops/recreates backed-up VIOS tables and sequences inside that one DB, intentionally removing the new nullable column/index; it must not be run against an active application. Existing post-upgrade files that did not exist at the snapshot remain quarantined/evidenced rather than being silently erased. Do not restore or overwrite agent-reports/history/investigations/rules merely to revert VIOS: those stores are outside its migration. Restart the exact cached old streamprocessor once DB/files/config match, then compare full original IDs/counts/hashes and reopen the saved report/evidence. Extra new immutable media may be preserved separately; do not claim an exact rollback if any original referenced file was not recovered.

No source finding requires a non-additive migration. Subsequent main cutover validation passed the paired backup, disposable restore, additive-schema baseline and preservation of original recording/report hashes; see the [current runtime receipt](../2026-10-20-vss33-spark.md). Remaining limits: an actual old-binary/new-schema round-trip has not been rehearsed, and no RTSP/live workload was exercised. Final native full-tail/seek qualification is recorded separately in that receipt.
