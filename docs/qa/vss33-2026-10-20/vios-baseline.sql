\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT json_build_object('table', table_name, 'column', column_name,
  'type', data_type, 'nullable', is_nullable, 'default', column_default)
FROM information_schema.columns WHERE table_schema='public'
ORDER BY table_name, ordinal_position;
SELECT json_build_object('table', tablename, 'index', indexname, 'definition', indexdef)
FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname;
SELECT format('SELECT json_build_object(''table'', %L, ''rows'', count(*), ''max_row_id'', max(row_id)) FROM %I.%I;',
  tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename
\gexec
SELECT json_build_object('sensor_id',sensor_id,'type',type,'row_id',row_id)
FROM sensor_details ORDER BY sensor_id;
SELECT json_build_object('sensor_id',sensor_id,'stream_id',stream_id,'row_id',row_id)
FROM sensor_streams ORDER BY sensor_id,stream_id;
SELECT json_build_object('row_id',row_id,'sensor_id',sensor_id,'stream_id',stream_id,
  'bytes',file_size,'duration_ms',file_duration,'start_time',start_time,'path',file_path)
FROM video_record_details ORDER BY row_id;
SELECT json_build_object('row_id',row_id,'stream_id',stream_id,'file_type',file_type,
  'file_path',file_path,'expiry_timestamp',expiry_timestamp,'bytes',file_size)
FROM temp_video_files ORDER BY row_id;
SELECT json_build_object('device_id',id) FROM local_device_details;
SELECT json_build_object('db_version',db_version) FROM db_details;
COMMIT;
