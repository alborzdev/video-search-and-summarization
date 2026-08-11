# Evidence: idempotent realtime rule replay on Thor

On 2026-08-11, the rebuilt Thor-local Alert Bridge completed a fresh replay
run in 29,874 ms using one uniquely owned local RTSP stream and one persisted
realtime VLM rule.

Rule creation returned an active durable record and one RT-VLM stream. Two
successive `POST /api/v1/realtime/replay` calls each reported exactly one
successful replay and zero failures. After each call there was exactly one
matching public rule, one Elasticsearch document, and one RT-VLM stream. The
server-generated rule identity, `created_at`, complete immutable rule
configuration, and stream identity remained unchanged; `last_replay_at`
advanced on the second call. RT-VLM worker evidence showed created/removed
counts of `1/0` after create, `2/1` after replay one, `3/2` after replay two,
and `3/3` after cleanup. There was exactly one live caption query throughout
instead of the three concurrent workers exposed by the pre-fix audit.

The rule was deleted once and an immediate repeated delete returned explicit
not-found. The publisher stopped, no owned VLM incident remained, and the
public-rule, persisted-rule, and unrelated RT-VLM catalog hashes exactly
matched their pre-run values. The harness made zero Agent `/generate` calls
and retained no runtime UUID or RTSP URL.

The schema-validated `runtime-receipt.json` is the machine-readable evidence.
