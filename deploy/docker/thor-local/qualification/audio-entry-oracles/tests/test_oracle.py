from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

HERE = Path(__file__).resolve().parents[1]
GIB = 1024**3
PHRASE = "Attention operator. The blue crate is ready."


def _module():
    spec = importlib.util.spec_from_file_location(
        "audio_entry_oracle", HERE / "oracle.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _artifact(
    tmp_path: Path,
    artifact_id: str,
    content: str | bytes,
    source_service: str,
    captured_at: str = "2026-08-01T12:01:00Z",
) -> dict:
    raw = content.encode() if isinstance(content, str) else content
    path = tmp_path / f"{artifact_id}.artifact"
    path.write_bytes(raw)
    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "sha256": _sha(raw),
        "size_bytes": len(raw),
        "captured_at": captured_at,
        "source_service": source_service,
    }


def _receipt(media_name: str, media_sha: str, media_size: int) -> dict:
    return {
        "schema_version": 1,
        "fixture_id": "vss-tiny-known-speech-h264-aac-v1",
        "purpose": "candidate_input_only",
        "capability_gap_ids": [
            "manifest-gap.audio-understanding.00-audio-aware-base-workflow",
            "manifest-gap.audio-understanding.01-audio-transcript-per-rt-vlm-chunk",
            "manifest-gap.audio-understanding.02-audio-aware-summarization-and-alerts",
        ],
        "phrase": {
            "text": PHRASE,
            "utf8_sha256": (
                "c20db4dfe2b82f3a2ebeb1cfc053e7b63baa3cf079140466827342930d641ec8"
            ),
        },
        "generator": {
            "recipe_sha256": (
                "ef0765520b8efae3cd2258762cd9a0c20d9cfdc2360611aa8776139571589a3c"
            ),
            "receipt_schema_sha256": (
                "11b379f215d54ae6c7fdc42e5680059a69d2b5a41b162d257b313e9ad3f11793"
            ),
            "video_source": "lavfi-color-plus-drawtext",
            "audio_source": "lavfi-flite",
            "tool_provenance": {
                "ffmpeg": {"path": "/usr/bin/ffmpeg", "sha256": "1" * 64},
                "ffprobe": {"path": "/usr/bin/ffprobe", "sha256": "2" * 64},
            },
        },
        "media": {
            "filename": media_name,
            "sha256": media_sha,
            "size_bytes": media_size,
            "max_size_bytes": 2_000_000,
        },
        "probe": {
            "format_names": ["mp4"],
            "duration_ms": 5800,
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "profile": "High",
                    "width": 320,
                    "height": 240,
                    "pix_fmt": "yuv420p",
                    "r_frame_rate": "10/1",
                    "duration_ms": 5800,
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "profile": "LC",
                    "sample_rate_hz": 48000,
                    "channels": 1,
                    "channel_layout": "mono",
                    "duration_ms": 5800,
                },
            ],
        },
        "safety": {
            "generated_outside_repository": True,
            "warehouse_data_used": False,
            "network_used": False,
            "docker_used": False,
            "model_loaded": False,
            "subprocesses": ["ffmpeg", "ffprobe"],
        },
    }


def _valid_evidence(tmp_path: Path) -> dict:
    media = _artifact(
        tmp_path,
        "fixture-media",
        b"bounded-fake-mp4",
        "fixture-generator",
        "2026-08-01T11:50:00Z",
    )
    media_path = tmp_path / "fixture.mp4"
    Path(media["path"]).rename(media_path)
    media["path"] = str(media_path)
    receipt_doc = _receipt(
        Path(media["path"]).name, media["sha256"], media["size_bytes"]
    )
    receipt = _artifact(
        tmp_path,
        "fixture-receipt",
        json.dumps(receipt_doc),
        "fixture-generator",
        "2026-08-01T11:50:00Z",
    )
    revision = "a" * 40
    model_manifest_doc = {
        "schema_version": 1,
        "repository": "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8",
        "revision": revision,
        "config": {
            "architectures": ["NemotronH_Nano_VL_V2ForConditionalGeneration"],
            "model_type": "nemotron_h",
        },
        "file_count": 1,
        "total_bytes": 123,
        "files": [{"path": "config.json", "sha256": "3" * 64, "size": 123}],
    }
    model_manifest = _artifact(
        tmp_path,
        "model-manifest",
        json.dumps(model_manifest_doc),
        "thor-host",
        "2026-08-01T11:55:00Z",
    )
    native_models = _artifact(
        tmp_path,
        "native-models",
        '{"id":"nemotron-omni-local","audio_support":true}',
        "rtvi-vlm",
    )
    native_launch = _artifact(
        tmp_path,
        "native-launch",
        (
            "nemotron-omni-local VLM_MODEL_SUPPORTS_AUDIO=true "
            "ENABLE_AUDIO=true http://127.0.0.1:8018 "
            "snapshot-verified=true "
            "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8 "
            f"{revision}"
        ),
        "thor-host",
    )
    transcript_models = _artifact(
        tmp_path,
        "transcript-models",
        '{"id":"qwen-local","audio_support":false}',
        "rtvi-vlm",
        "2026-08-01T12:12:00Z",
    )
    asr_creation = _artifact(
        tmp_path,
        "asr-creation",
        (
            "Creating ASR process for audio transcription "
            "VLM_MODEL_SUPPORTS_AUDIO=false parakeet-local"
        ),
        "rtvi-vlm",
        "2026-08-01T12:12:00Z",
    )
    native_memory = _artifact(
        tmp_path,
        "native-memory",
        (
            f"total_bytes={128 * GIB} available_before_bytes={100 * GIB} "
            f"available_during_bytes={30 * GIB} available_after_bytes={90 * GIB} "
            "gate_passed=true oom_events=0"
        ),
        "thor-host",
    )
    transcript_resources = _artifact(
        tmp_path,
        "transcript-resources",
        (
            f"memory_limit_bytes={8 * GIB} peak_memory_bytes={4 * GIB} "
            "cpu_limit_cores=8 peak_cpu_cores=4 "
            "within_declared_budget=true oom_events=0"
        ),
        "thor-host",
        "2026-08-01T12:12:00Z",
    )
    base_response = _artifact(
        tmp_path, "base-response", f"The response heard: {PHRASE}", "vss-agent"
    )
    base_control = _artifact(
        tmp_path,
        "base-control",
        "The video shows a title card; no audible detail was used.",
        "vss-agent",
    )
    chunk_response = _artifact(
        tmp_path,
        "chunk-response",
        f'{{"audio_transcript":"{PHRASE}"}}',
        "rtvi-vlm",
        "2026-08-01T12:12:00Z",
    )
    summary = _artifact(
        tmp_path, "summary", f"The summary reports: {PHRASE}", "lvs-server"
    )
    summary_control = _artifact(
        tmp_path,
        "summary-control",
        "The silent control contains only a title card.",
        "lvs-server",
    )
    alert = _artifact(tmp_path, "alert", f"Audio alert: {PHRASE}", "alert-bridge")
    alert_control = _artifact(
        tmp_path,
        "alert-control",
        "No audio-derived alert was generated.",
        "alert-bridge",
    )
    cleanup = _artifact(
        tmp_path,
        "cleanup",
        "audioq:native-run audioq:transcript-run cleanup-complete",
        "operator-cleanup",
        "2026-08-01T12:21:00Z",
    )
    return {
        "schema_version": 1,
        "purpose": "candidate_runtime_evidence_for_review_only",
        "candidate_status": "observed_not_admitted",
        "live_ledger_mutation": False,
        "warehouse_sample_bundle": False,
        "fixture": {
            "fixture_id": "vss-tiny-known-speech-h264-aac-v1",
            "phrase": PHRASE,
            "phrase_utf8_sha256": (
                "c20db4dfe2b82f3a2ebeb1cfc053e7b63baa3cf079140466827342930d641ec8"
            ),
            "receipt": receipt,
            "media": media,
        },
        "native_audio_run": {
            "run_id": "native-run",
            "authorization_id": "authorization-native",
            "host_architecture": "aarch64",
            "host_model": "NVIDIA Jetson AGX Thor",
            "started_at": "2026-08-01T12:00:00Z",
            "ended_at": "2026-08-01T12:10:00Z",
            "endpoint": {
                "base_url": "http://127.0.0.1:8018",
                "models_url": "http://127.0.0.1:8018/v1/models",
                "transport": "loopback_http",
                "scope": "loopback_only",
                "provider": "local_rt_vlm",
            },
            "model": {
                "repository": ("nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8"),
                "revision": revision,
                "configured_model_id": "nemotron-omni-local",
                "observed_model_id": "nemotron-omni-local",
                "backend": "vllm-compatible",
                "audio_support": True,
                "vlm_model_supports_audio": True,
                "enable_audio": True,
                "asr_process_state": "skipped_native_audio",
                "snapshot_manifest": model_manifest,
                "models_response": native_models,
                "launch_capture": native_launch,
            },
            "memory": {
                "total_bytes": 128 * GIB,
                "available_before_bytes": 100 * GIB,
                "available_during_bytes": 30 * GIB,
                "available_after_bytes": 90 * GIB,
                "minimum_available_bytes": 80 * GIB,
                "gpu_memory_utilization": 0.45,
                "fixed_reserve_ratio": 0.2,
                "vlm_batch_size": 1,
                "num_vlm_processes": 1,
                "max_model_sequences": 1,
                "oom_events": 0,
                "gate_passed": True,
                "capture": native_memory,
            },
        },
        "transcript_run": {
            "run_id": "transcript-run",
            "authorization_id": "authorization-transcript",
            "host_architecture": "aarch64",
            "host_model": "NVIDIA Jetson AGX Thor",
            "started_at": "2026-08-01T12:11:00Z",
            "ended_at": "2026-08-01T12:20:00Z",
            "endpoint": {
                "base_url": "http://127.0.0.1:8018",
                "models_url": "http://127.0.0.1:8018/v1/models",
                "transport": "loopback_http",
                "scope": "loopback_only",
                "provider": "local_rt_vlm",
            },
            "model": {
                "configured_model_id": "qwen-local",
                "observed_model_id": "qwen-local",
                "backend": "openai-compat",
                "audio_support": False,
                "vlm_model_supports_audio": False,
                "enable_audio": True,
                "models_response": transcript_models,
            },
            "asr": {
                "provider": "local_riva",
                "process_state": "created_and_healthy",
                "endpoint": "grpc://127.0.0.1:50051",
                "model_id": "parakeet-local",
                "model_revision": "b" * 64,
                "health_passed": True,
                "creation_capture": asr_creation,
            },
            "resources": {
                "memory_limit_bytes": 8 * GIB,
                "peak_memory_bytes": 4 * GIB,
                "cpu_limit_cores": 8,
                "peak_cpu_cores": 4,
                "oom_events": 0,
                "within_declared_budget": True,
                "capture": transcript_resources,
            },
        },
        "oracle_evidence": [
            {
                "entry_id": (
                    "manifest-gap.audio-understanding.00-audio-aware-base-workflow"
                ),
                "oracle_id": "oracle.manifest-entry.audio-understanding.00",
                "candidate_observation": "observed_not_admitted",
                "run_id": "native-run",
                "request_enable_audio": True,
                "known_phrase": PHRASE,
                "response_text": f"The response heard: {PHRASE}",
                "audio_disabled_control_text": (
                    "The video shows a title card; no audible detail was used."
                ),
                "response_capture": base_response,
                "control_capture": base_control,
                "cleanup_evidence_id": "cleanup-audio",
            },
            {
                "entry_id": (
                    "manifest-gap.audio-understanding.01-"
                    "audio-transcript-per-rt-vlm-chunk"
                ),
                "oracle_id": "oracle.manifest-entry.audio-understanding.01",
                "candidate_observation": "observed_not_admitted",
                "run_id": "transcript-run",
                "request_enable_audio": True,
                "asr_required": True,
                "native_omni_asr_skip_accepted": False,
                "chunks": [
                    {
                        "chunk_index": 0,
                        "start_ms": 0,
                        "end_ms": 5800,
                        "audio_transcript": PHRASE,
                        "asr_started_ms": 10,
                        "asr_ended_ms": 800,
                        "response_capture": chunk_response,
                    }
                ],
                "cleanup_evidence_id": "cleanup-audio",
            },
            {
                "entry_id": (
                    "manifest-gap.audio-understanding.02-"
                    "audio-aware-summarization-and-alerts"
                ),
                "oracle_id": "oracle.manifest-entry.audio-understanding.02",
                "candidate_observation": "observed_not_admitted",
                "run_id": "native-run",
                "request_enable_audio": True,
                "summary_text": f"The summary reports: {PHRASE}",
                "summary_audio_disabled_control_text": (
                    "The silent control contains only a title card."
                ),
                "alert_text": f"Audio alert: {PHRASE}",
                "alert_audio_disabled_control_text": (
                    "No audio-derived alert was generated."
                ),
                "alert_category": "audio-known-phrase",
                "summary_capture": summary,
                "summary_control_capture": summary_control,
                "alert_capture": alert,
                "alert_control_capture": alert_control,
                "cleanup_evidence_id": "cleanup-audio",
            },
        ],
        "cleanup": {
            "cleanup_evidence_id": "cleanup-audio",
            "completed_at": "2026-08-01T12:21:00Z",
            "ownership_prefix": "audioq:",
            "created_resource_ids": ["audioq:native-run", "audioq:transcript-run"],
            "removed_resource_ids": ["audioq:native-run", "audioq:transcript-run"],
            "preexisting_resources_unchanged": True,
            "broad_delete_used": False,
            "native_services_stopped": True,
            "transcript_services_stopped": True,
            "remaining_stream_ids": [],
            "fixture_media_preserved": True,
            "capture": cleanup,
        },
    }


def _write_evidence(tmp_path: Path, evidence: dict) -> Path:
    path = tmp_path / "candidate-evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    return path


def _update_artifact(artifact: dict, content: str) -> None:
    raw = content.encode()
    Path(artifact["path"]).write_bytes(raw)
    artifact["sha256"] = _sha(raw)
    artifact["size_bytes"] = len(raw)


def test_plan_is_inert_exact_and_schema_valid():
    module = _module()
    result = module.build_plan()
    assert len(result["source_checks"]) == 23
    assert result["oracle_count"] == 3
    assert result["runtime_evidence"] == []
    assert result["warehouse_sample_bundle"] == "excluded"
    assert not any(
        result[key]
        for key in (
            "writes",
            "subprocesses",
            "docker",
            "network",
            "lifecycle",
            "model_load",
            "downloads",
            "credentials",
        )
    )


def test_package_schemas_and_raw_identities_are_exact():
    module = _module()
    for filename, digest in module.EXPECTED_PACKAGE_HASHES.items():
        path = HERE / filename
        assert _sha(path.read_bytes()) == digest
        if "schema" in filename:
            jsonschema.Draft202012Validator.check_schema(json.loads(path.read_text()))


def test_valid_future_evidence_is_candidate_only(tmp_path):
    module = _module()
    evidence = _valid_evidence(tmp_path)
    result = module.validate_evidence(_write_evidence(tmp_path, evidence))
    assert result["candidate_status"] == "validated_for_review_not_admitted"
    assert result["can_mark_passed_current"] is False
    assert result["runtime_evidence_admitted"] == []
    assert result["warehouse_sample_bundle"] == "excluded"
    assert all(result["checks"].values())


def test_native_omni_asr_skip_never_proves_transcript(tmp_path):
    module = _module()
    evidence = _valid_evidence(tmp_path)
    capture = evidence["transcript_run"]["asr"]["creation_capture"]
    _update_artifact(
        capture,
        (
            "Creating ASR process for audio transcription "
            "VLM_MODEL_SUPPORTS_AUDIO=false parakeet-local "
            "Skipping ASR process - VLM handles audio natively"
        ),
    )
    with pytest.raises(
        module.QualificationError, match="ASR-skip evidence cannot prove"
    ):
        module.validate_evidence(_write_evidence(tmp_path, evidence))


def test_native_and_asr_lanes_require_distinct_authorization_ids(tmp_path):
    module = _module()
    evidence = _valid_evidence(tmp_path)
    evidence["transcript_run"]["authorization_id"] = evidence["native_audio_run"][
        "authorization_id"
    ]
    with pytest.raises(module.QualificationError, match="runs must be distinct"):
        module.validate_evidence(_write_evidence(tmp_path, evidence))


def test_asr_interval_must_be_within_its_exact_media_chunk(tmp_path):
    module = _module()
    evidence = _valid_evidence(tmp_path)
    evidence["oracle_evidence"][1]["chunks"][0].update(
        asr_started_ms=500_000, asr_ended_ms=500_100
    )
    with pytest.raises(module.QualificationError, match="timing is invalid"):
        module.validate_evidence(_write_evidence(tmp_path, evidence))


def test_asr_creation_capture_requires_rtvi_vlm_source(tmp_path):
    module = _module()
    evidence = _valid_evidence(tmp_path)
    evidence["transcript_run"]["asr"]["creation_capture"][
        "source_service"
    ] = "fixture-generator"
    with pytest.raises(module.QualificationError, match="originate from RT-VLM"):
        module.validate_evidence(_write_evidence(tmp_path, evidence))


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ((0, "response_text"), "No speech was understood.", "Base response lacks"),
        ((2, "summary_text"), "A box is visible.", "LVS summary lacks"),
        ((2, "alert_text"), "A generic event happened.", "alert lacks"),
        ((1, "chunks", 0, "audio_transcript"), "unrelated speech", "exactly one"),
        (
            (0, "audio_disabled_control_text"),
            "The blue crate is ready.",
            "Base control leaks",
        ),
    ],
)
def test_phrase_and_control_correlations_fail_closed(tmp_path, path, value, message):
    module = _module()
    evidence = _valid_evidence(tmp_path)
    target = evidence["oracle_evidence"][path[0]]
    if len(path) == 2:
        target[path[1]] = value
    else:
        target[path[1]][path[2]][path[3]] = value
        _update_artifact(
            target["chunks"][0]["response_capture"],
            f'{{"audio_transcript":"{value}"}}',
        )
    with pytest.raises(module.QualificationError, match=message):
        module.validate_evidence(_write_evidence(tmp_path, evidence))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda evidence: evidence["oracle_evidence"][1]["chunks"][0].update(
                start_ms=200
            ),
            "overlap or large gap",
        ),
        (
            lambda evidence: evidence["oracle_evidence"][1]["chunks"][0].update(
                asr_started_ms=900, asr_ended_ms=800
            ),
            "timing is invalid",
        ),
        (
            lambda evidence: evidence["native_audio_run"]["memory"].update(
                available_before_bytes=80 * GIB
            ),
            "memory gate",
        ),
        (
            lambda evidence: evidence["native_audio_run"]["memory"].update(
                available_during_bytes=20 * GIB
            ),
            "memory gate",
        ),
        (
            lambda evidence: evidence["transcript_run"]["resources"].update(
                peak_memory_bytes=9 * GIB
            ),
            "resource budget",
        ),
    ],
)
def test_timing_and_resource_gates_fail_closed(tmp_path, mutate, message):
    module = _module()
    evidence = _valid_evidence(tmp_path)
    mutate(evidence)
    with pytest.raises(module.QualificationError, match=message):
        module.validate_evidence(_write_evidence(tmp_path, evidence))


def test_model_identity_endpoint_and_provenance_fail_closed(tmp_path):
    module = _module()
    mutations = [
        (
            lambda evidence: evidence["native_audio_run"]["model"].update(
                observed_model_id="different-model"
            ),
            "model identities differ",
        ),
        (
            lambda evidence: evidence["native_audio_run"]["endpoint"].update(
                models_url="http://127.0.0.1:8019/v1/models"
            ),
            "not locally bound",
        ),
        (
            lambda evidence: _update_artifact(
                evidence["native_audio_run"]["model"]["snapshot_manifest"],
                json.dumps(
                    {
                        "repository": "wrong/repository",
                        "revision": "a" * 40,
                        "file_count": 1,
                        "total_bytes": 1,
                        "files": [{"path": "x"}],
                    }
                ),
            ),
            "snapshot provenance",
        ),
        (
            lambda evidence: _update_artifact(
                evidence["native_audio_run"]["model"]["models_response"],
                "nemotron-omni-local audio_support true",
            ),
            "invalid JSON",
        ),
        (
            lambda evidence: _update_artifact(
                evidence["native_audio_run"]["model"]["models_response"],
                json.dumps({"id": "nemotron-omni-local", "audio_support": False}),
            ),
            "identity or audio_support differs",
        ),
        (
            lambda evidence: _update_artifact(
                evidence["native_audio_run"]["model"]["snapshot_manifest"],
                json.dumps(
                    {
                        "repository": "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8",
                        "revision": "a" * 40,
                        "file_count": 1,
                        "total_bytes": 123,
                        "files": [{"garbage": True}],
                    }
                ),
            ),
            "snapshot file entry is invalid",
        ),
        (
            lambda evidence: _update_artifact(
                evidence["native_audio_run"]["model"]["snapshot_manifest"],
                json.dumps(
                    {
                        "repository": "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8",
                        "revision": "a" * 40,
                        "file_count": 1,
                        "total_bytes": 999,
                        "files": [
                            {"path": "config.json", "sha256": "3" * 64, "size": 123}
                        ],
                    }
                ),
            ),
            "file count or size sum differs",
        ),
    ]
    for mutate, message in mutations:
        evidence = _valid_evidence(tmp_path)
        mutate(evidence)
        with pytest.raises(module.QualificationError, match=message):
            module.validate_evidence(_write_evidence(tmp_path, evidence))


def test_cleanup_is_exact_owned_and_post_run(tmp_path):
    module = _module()
    mutations = [
        (
            lambda evidence: evidence["cleanup"].update(
                removed_resource_ids=["audioq:native-run", "audioq:other"]
            ),
            "exactly executor-owned",
        ),
        (
            lambda evidence: evidence["cleanup"].update(
                created_resource_ids=["foreign:native-run", "audioq:transcript-run"],
                removed_resource_ids=["foreign:native-run", "audioq:transcript-run"],
            ),
            "ownership prefix",
        ),
        (
            lambda evidence: evidence["cleanup"].update(
                created_resource_ids=["audioq:one", "audioq:two"],
                removed_resource_ids=["audioq:one", "audioq:two"],
            ),
            "bound to both run ids",
        ),
        (
            lambda evidence: evidence["cleanup"].update(
                completed_at="2026-08-01T12:05:00Z"
            ),
            "before a runtime lane ended",
        ),
        (
            lambda evidence: evidence["transcript_run"].update(
                started_at="2026-08-01T12:09:00Z"
            ),
            "runs must be distinct",
        ),
        (
            lambda evidence: evidence["cleanup"]["capture"].update(
                captured_at="2026-08-01T12:19:00Z"
            ),
            "outside cleanup",
        ),
    ]
    for mutate, message in mutations:
        evidence = _valid_evidence(tmp_path)
        mutate(evidence)
        with pytest.raises(module.QualificationError, match=message):
            module.validate_evidence(_write_evidence(tmp_path, evidence))


def test_artifact_digest_duplicate_path_and_symlink_fail_closed(tmp_path):
    module = _module()
    evidence = _valid_evidence(tmp_path)
    evidence["oracle_evidence"][0]["response_capture"]["sha256"] = "0" * 64
    with pytest.raises(module.QualificationError, match="digest mismatch"):
        module.validate_evidence(_write_evidence(tmp_path, evidence))

    evidence = _valid_evidence(tmp_path)
    evidence["oracle_evidence"][0]["control_capture"]["path"] = evidence[
        "oracle_evidence"
    ][0]["response_capture"]["path"]
    with pytest.raises(module.QualificationError, match="path reused"):
        module.validate_evidence(_write_evidence(tmp_path, evidence))

    evidence = _valid_evidence(tmp_path)
    artifact = evidence["oracle_evidence"][0]["response_capture"]
    target = Path(artifact["path"])
    link = tmp_path / "response-link"
    link.symlink_to(target)
    artifact["path"] = str(link)
    with pytest.raises(module.QualificationError, match="regular non-symlink"):
        module.validate_evidence(_write_evidence(tmp_path, evidence))


def test_schema_extension_duplicate_json_and_relative_path_are_rejected(tmp_path):
    module = _module()
    evidence = _valid_evidence(tmp_path)
    evidence["unexpected"] = True
    with pytest.raises(module.QualificationError, match="schema violation"):
        module.validate_evidence(_write_evidence(tmp_path, evidence))

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(module.QualificationError, match="duplicate JSON key"):
        module.validate_evidence(duplicate)

    with pytest.raises(module.QualificationError, match="path must be absolute"):
        module.validate_evidence(Path("relative.json"))


def test_source_and_package_identity_drift_fail_closed(tmp_path, monkeypatch):
    module = _module()
    target = "services/rtvi/rt-vlm/src/vlm_pipeline/vlm_pipeline.py"
    tampered = tmp_path / "tampered-source"
    tampered.write_text("tampered", encoding="utf-8")
    original_repo_file = module._repo_file
    monkeypatch.setattr(
        module,
        "_repo_file",
        lambda relative: (
            tampered if relative == target else original_repo_file(relative)
        ),
    )
    with pytest.raises(module.QualificationError, match="source lock"):
        module.build_plan()

    module = _module()
    module.EXPECTED_PACKAGE_HASHES["evidence.schema.json"] = "0" * 64
    with pytest.raises(module.QualificationError, match="package identity drift"):
        module.build_plan()


def test_oracle_ast_has_no_network_subprocess_mutation_or_dynamic_execution():
    tree = ast.parse((HERE / "oracle.py").read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported.intersection(
        {
            "builtins",
            "httpx",
            "os",
            "requests",
            "shutil",
            "socket",
            "subprocess",
            "tempfile",
            "urllib",
        }
    )
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called.intersection({"open", "exec", "eval", "compile", "__import__"})
    attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not attributes.intersection(
        {
            "chmod",
            "hardlink_to",
            "link_to",
            "mkdir",
            "open",
            "rename",
            "replace",
            "rmdir",
            "symlink_to",
            "touch",
            "unlink",
            "write_bytes",
            "write_text",
        }
    )
