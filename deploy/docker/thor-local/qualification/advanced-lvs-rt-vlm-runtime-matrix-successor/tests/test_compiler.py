from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("advanced_runtime_matrix_compiler", HERE / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def test_matrix_is_exactly_checked_in() -> None:
    value = compiler.build_matrix()
    assert compiler.MATRIX_PATH.read_bytes() == compiler._render(value)


def test_matrix_validates_against_strict_schema() -> None:
    value = compiler.build_matrix()
    schema = json.loads(compiler.MATRIX_SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)


def test_sixty_four_exact_official_rows_have_current_runtime_evidence() -> None:
    matrix = compiler.build_matrix()
    assert [row["official_index"] for row in matrix["rows"]] == [
        69, 70, 204, 205, 299, 300, 302, 333, 336, 337, 339, 340, 341, 342, 343, 344, 345, 347, 348, 349, 350, 353, 354, 364, 365, 366, 367, 368, 369, 370, 371, 372, 373, 374, 375, 376, 377, 378, 379, 380, 381, 382, 392, 393, 394, 395, 397, 398, 399, 400, 401, 402, 403, 404, 412, 413, 415, 416, 417, 420, 421, 422, 424, 467
    ]
    assert all(row["overlay_runtime_state"] == "passed_current_thor" for row in matrix["rows"])
    assert all(row["runtime_evidence"]["receipt_sha256"] for row in matrix["rows"])


def test_overlay_does_not_falsify_canonical_admission() -> None:
    matrix = compiler.build_matrix()
    assert matrix["summary"]["canonical_promotions"] == 0
    assert matrix["matrix_semantics"]["canonical_admission_claimed"] is False
    assert all(row["canonical_runtime_state"] == "not_qualified" for row in matrix["rows"])
    assert all(row["canonical_state_advanced"] is False for row in matrix["rows"])


def test_behavior_dynamic_control_receipt_is_bound_to_both_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "behavior-analytics-dynamic-control-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [204, 205]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
    assert receipt["dynamic_configuration"]["passed"] == 24
    assert receipt["dynamic_calibration"]["passed"] == 7
    assert receipt["dynamic_calibration"]["immutable_existing_type"]["type_switch_markers_after_update"] == 0


def test_receipts_are_source_locked_schema_valid_and_privacy_safe() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    for entry in contract["entries"]:
        receipt = compiler._validate_receipt(entry)
        assert receipt["contract_sha256"] == entry["contract_sha256"]


def test_multi_capability_receipt_is_bound_to_both_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-file-dense-captions-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [336, 342]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]


def test_openai_api_receipt_is_bound_to_six_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-openai-api-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [347, 348, 349, 350, 353, 354]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]


def test_local_media_receipt_is_bound_to_two_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-local-media-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [339, 340]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]


def test_http_s_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-http-s-runtime-successor"
    )
    assert entry["official_index"] == 337
    receipt = compiler._validate_receipt(entry)
    assert entry["capability_id"] in receipt["capability_ids"]


def test_rtsp_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-rtsp-runtime-successor"
    )
    assert entry["official_index"] == 341
    receipt = compiler._validate_receipt(entry)
    assert entry["capability_id"] in receipt["capability_ids"]
    assert receipt["live_caption_sse"]["markers_in_chronological_order"] is True
    assert receipt["cleanup"]["owned_stream_absent"] is True


def test_incident_category_receipt_is_bound_to_both_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-incidents-categories-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [343, 344]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
    assert receipt["kafka_incident"]["owned_matching_records"] == 1
    assert receipt["cleanup"]["append_only_kafka_record_count"] == 1


def test_asset_limits_expiry_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-asset-limits-expiry-runtime-successor"
    )
    assert entry["official_index"] == 364
    receipt = compiler._validate_receipt(entry)
    assert receipt["storage_limit"]["hard_limit"]["error"]["status_code"] == 503
    assert receipt["ttl_expiry"]["ttl"]["busy_expired_asset_preserved"] is True


def test_prometheus_otel_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-prometheus-otel-runtime-successor"
    )
    assert entry["official_index"] == 366
    receipt = compiler._validate_receipt(entry)
    assert receipt["prometheus_query"]["up_value"] == 1
    assert receipt["opentelemetry"]["console_span_export_present"] is True


def test_error_publication_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-error-publication-runtime-successor"
    )
    assert entry["official_index"] == 365
    receipt = compiler._validate_receipt(entry)
    assert receipt["kafka"]["message_type_header_exact"] is True
    assert receipt["redis"]["backend_switch_routed_to_redis"] is True
    assert receipt["schema_equal_between_backends"] is True
    assert receipt["cleanup"]["kafka_topic_absent"] is True


def test_rt_embed_multimodal_receipt_is_bound_to_both_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-embed-multimodal-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [368, 371]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
    assert receipt["text_embedding"]["vector_dimension"] == 768
    assert receipt["image_embedding"]["inference"]["chunk_count"] == 1
    assert receipt["video_embedding"]["inference"]["chunk_count"] == 2
    assert receipt["model"]["cosmos_embed1_source_exact"] is True


def test_rt_embed_live_api_receipt_is_bound_to_three_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-embed-live-api-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [369, 373, 374]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
    assert receipt["live_rtsp"]["embedding_dimension"] == 768
    assert receipt["stream_apis"]["complete_operation_count"] == 24
    assert receipt["health_metadata_models_metrics"]["metrics_http_200_and_prometheus"] is True


def test_rt_embed_url_brokers_otel_receipt_is_bound_to_two_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-embed-url-brokers-otel-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [370, 372]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
    assert receipt["url_and_inline_base64"]["same_fixture_bytes"] is True
    assert receipt["kafka"]["result_message_count"] == 2
    assert receipt["redis"]["error_message_count"] == 1
    assert receipt["opentelemetry"]["configured_service_name_exact"] is True


def test_rt_cv_2d_core_receipt_is_bound_to_four_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-cv-2d-core-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [375, 380, 381, 382]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
    assert receipt["file_detection_tracking"]["detection_tracking"]["frames"] == 8
    assert receipt["rtsp_detection_tracking"]["detection_tracking"]["frames"] == 8
    assert receipt["dynamic_stream_lifecycle"]["final_stream_count"] == 0
    assert receipt["thor_vpi_tracker"]["vpi_error_count_after_clean_start"] == 0


def test_rt_cv_model_variants_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-cv-model-variants-runtime-successor"
    )
    assert entry["official_index"] == 376
    receipt = compiler._validate_receipt(entry)
    assert receipt["warehouse_rtdetr"]["class_map_person_and_pallet"] is True
    assert receipt["smart_city_rtdetr"]["configuration"]["detector_backend"] == "nvinfer"
    assert receipt["smart_city_rtdetr"]["detection_tracking"]["frames"] == 8
    assert receipt["smart_city_gdino"]["configuration"]["detector_backend"] == "triton"
    assert receipt["smart_city_gdino"]["configuration"]["prompt_class"] == "person"
    assert receipt["smart_city_gdino"]["detection_tracking"]["frames"] == 8


def test_rt_cv_siglip2_reidentification_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-cv-siglip2-reidentification-runtime-successor"
    )
    assert entry["official_index"] == 378
    receipt = compiler._validate_receipt(entry)
    proof = receipt["reidentification"]
    assert receipt["artifact_identity"]["embedding_dimension"] == 1152
    assert proof["full_two_cycle_boundary_observed"] is True
    assert proof["embedding_dimensions"] == [1152]
    assert proof["finite_embeddings"] is True
    assert proof["distinct_track_ids_reassociated"] is True
    assert proof["positive_cosine_min"] >= 0.99
    assert receipt["negative_preflight"]["mismatched_tokenizer_rejected"] is True


def test_rt_cv_radio_clip_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["capability_id"] == "manifest-entry.rt-cv-2d.02-radio-clip"
    )
    assert entry["official_index"] == 377
    receipt = compiler._validate_receipt(entry)
    proof = receipt["reidentification"]
    assert receipt["artifact_identity"]["embedding_dimension"] == 1536
    assert proof["embedding_dimensions"] == [1536]
    assert proof["finite_embeddings"] is True
    assert proof["embedded_object_types"] == ["Pallet", "Person"]
    assert proof["object_track_pairs_with_embeddings"] >= 2
    assert receipt["negative_preflight"]["incompatible_dimension_configured"] == 1024
    assert receipt["negative_preflight"]["incompatible_dimension_rejected"] is True


def test_rt_cv_smart_infer_and_ofa_receipt_is_bound_to_two_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["capability_id"]
        in {"behavior.rt-cv.smart-infer", "behavior.rt-cv.ofa-predict"}
    ]
    assert [entry["official_index"] for entry in entries] == [69, 70]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
        assert receipt["configuration"]["vision_smart_infer"] == 1
        assert receipt["configuration"]["vision_ofa_predict"] == 1


def test_rt_cv_image_embedding_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-cv-image-embedding-runtime-successor"
    )
    assert entry["official_index"] == 379
    receipt = compiler._validate_receipt(entry)
    evidence = receipt["on_demand_image_embedding"]
    assert receipt["fixtures"]["format"] == "P6_PPM"
    assert evidence["active_streams_before"] == 0
    assert evidence["active_streams_after"] == 0
    assert evidence["same_image_vector_exact"] is True
    assert evidence["different_image_vector_distinct"] is True
    assert evidence["different_image_cosine"] < 0.99
    assert receipt["negative_path_validation"]["error_exact"] is True


def test_vios_file_lifecycle_receipt_is_bound_to_three_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "vios-file-lifecycle-manifest-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [412, 415, 416]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
        assert receipt["cleanup"]["exact_file_list_restored"] is True
        assert receipt["cleanup"]["exact_sensor_list_restored"] is True
    receipt = compiler._validate_receipt(entries[0])
    assert receipt["downloads"]["clip"]["distinct_from_full_file"] is True
    assert receipt["snapshot"]["visual_marker_correlated"] is True


def test_vios_file_rtsp_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "vios-file-rtsp-manifest-runtime-successor"
    )
    assert entry["official_index"] == 413
    receipt = compiler._validate_receipt(entry)
    assert entry["capability_id"] in receipt["capability_ids"]
    assert receipt["republish"]["automatic_output"] == "RTSP"
    assert receipt["republish"]["rtsp_video_codec"] == "h264"
    assert receipt["republish"]["webrtc_clock_advanced"] is True
    assert all(receipt["cleanup"].values())


def test_vios_live_replay_receipt_is_bound_to_exact_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entry = next(
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "vios-webrtc-live-replay-manifest-runtime-successor"
    )
    assert entry["official_index"] == 417
    receipt = compiler._validate_receipt(entry)
    assert entry["capability_id"] in receipt["capability_ids"]
    assert receipt["live"]["signaling_complete"] is True
    assert receipt["live"]["live_unmuted_video_track"] is True
    assert receipt["replay"]["signaling_complete"] is True
    assert receipt["replay"]["frames_continued_after_all_seeks"] is True
    assert receipt["replay"]["seek_forward_status"] == 200
    assert receipt["replay"]["ui_seek_status"] == 200
    assert receipt["replay"]["invalid_seek_status"] == 501
    assert receipt["cleanup"]["main_vios_restored"] is True


def test_vios_codec_receipt_is_bound_to_four_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "vios-codecs-manifest-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [420, 421, 422, 424]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
        assert receipt["cleanup"]["main_vios_unchanged"] is True
    receipt = compiler._validate_receipt(entries[0])
    assert receipt["b_frame_handling"]["decoded_frames"] == 120
    assert receipt["hevc_multislice_rfc7798"]["slices_per_picture"] == 4
    assert receipt["audio_rtsp_republish"]["working_transcode_substitute"] is True
    assert receipt["policy"]["audio_recording_claimed"] is False


def test_alert_websocket_receipt_is_bound_to_exact_candidate_row() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "alert-websocket-manifest-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [333]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
        assert receipt["delivery"]["alert_frame_count"] == 1
        assert receipt["delivery"]["pending_after_callback"] == 0
        assert receipt["cleanup"]["owned_streams_absent"] is True
    receipt = compiler._validate_receipt(entries[0])
    assert "protocol.alert.websocket" in receipt["capability_ids"]
    assert receipt["negative"]["socket_remained_open"] is True
    assert receipt["policy"]["slack_dependency"] == "excluded"


def test_video_analytics_and_va_mcp_receipt_is_bound_to_nine_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "video-analytics-va-mcp-manifest-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [
        397, 398, 399, 400, 401, 402, 403, 404, 467
    ]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]
    receipt = compiler._validate_receipt(entries[0])
    assert receipt["video_analytics_api"]["openapi_operations"] == 56
    assert receipt["video_analytics_api"]["data_bearing_gets_nonempty"] == 40
    assert receipt["va_mcp"]["tool_count"] == 9
    assert receipt["va_mcp"]["read_only_unique_tools"] == 8
    assert receipt["va_mcp"]["react_agent_advertised_not_invoked"] is True
    assert all(receipt["cleanup"].values())


def test_policy_excludes_agent_generate_and_warehouse_sample() -> None:
    matrix = compiler.build_matrix()
    assert matrix["summary"]["agent_generate_calls"] == 0
    assert matrix["summary"]["warehouse_sample_bundle"] == "excluded"
    assert all(row["warehouse_sample_bundle"] == "excluded" for row in matrix["rows"])
