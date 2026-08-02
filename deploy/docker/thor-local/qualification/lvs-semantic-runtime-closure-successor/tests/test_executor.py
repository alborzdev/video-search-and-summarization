from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lvs_closure_executor", HERE / "executor.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


ACK = "I_ACK_LVS_CLOSURE_RUNTIME_AND_LIVE_CAPTION_GENERATION"
MODEL = "local-lvs-model"
STREAM_ID = module._owned_stream_id("closure-test-run")
SENSOR_A = "11111111-1111-4111-8111-111111111111"
SENSOR_B = "22222222-2222-4222-8222-222222222222"
MEDIA_A = b"exact-vst-object-a"
MEDIA_B = b"exact-vst-object-b"


def manifest():
    return {
        "schema_version": 1,
        "run_id": "closure-test-run",
        "agent_origin": "http://127.0.0.1:8000",
        "lvs_origin": "http://127.0.0.1:8001",
        "rtvi_vlm_origin": "http://127.0.0.1:8018",
        "vst_origin": "http://127.0.0.1:8082",
        "elasticsearch_origin": "http://127.0.0.1:9200",
        "allowed_media_origins": ["http://127.0.0.1:8080"],
        "lvs_identity": {
            "version": "3.0.0",
            "sub_version": "deadbeef",
            "model": MODEL,
        },
        "fixtures": [
            {
                "sensor_id": SENSOR_A,
                "stored_media_sha256": module._sha(MEDIA_A),
                "stored_media_bytes": len(MEDIA_A),
                "duration_seconds": 61.000001,
                "owner_run_id": "closure-test-run",
                "ownership_attested": True,
            },
            {
                "sensor_id": SENSOR_B,
                "stored_media_sha256": module._sha(MEDIA_B),
                "stored_media_bytes": len(MEDIA_B),
                "duration_seconds": 62.000001,
                "owner_run_id": "closure-test-run",
                "ownership_attested": True,
            },
        ],
        "live_stream": {
            "id": STREAM_ID,
            "start_time": "2026-08-02T12:00:00.000Z",
            "end_time": "2026-08-02T12:01:00.000Z",
            "prompt": "Describe every visible event in this exclusive range.",
            "scenario": "traffic monitoring test range",
            "events": ["vehicle crossing"],
            "objects_of_interest": ["vehicle"],
            "chunk_duration": 10,
            "owner_run_id": "closure-test-run",
            "ownership_attested": True,
            "exclusive_range_attested": True,
            "exclusive_collection_attested": True,
        },
    }


def timelines():
    return {
        SENSOR_A: [
            {
                "startTime": "2026-08-02T10:00:00.000000Z",
                "endTime": "2026-08-02T10:01:01.000001Z",
            }
        ],
        SENSOR_B: [
            {
                "startTime": "2026-08-02T11:00:00.000000Z",
                "endTime": "2026-08-02T11:01:02.000001Z",
            }
        ],
        STREAM_ID: [
            {
                "startTime": "2026-08-02T12:00:00.000000Z",
                "endTime": "2026-08-02T12:01:00.000000Z",
            }
        ],
        "unrelated-sensor": [
            {
                "startTime": "2026-08-02T09:00:00.000000Z",
                "endTime": "2026-08-02T09:01:00.000000Z",
            }
        ],
    }


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class FakeTransport:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(
        self,
        *,
        drift_timeline=False,
        preexisting=False,
        wrong_media=False,
        bad_retrieval=False,
        bad_start=False,
        stop_status=200,
        reappear_after_cleanup=False,
        delivery_on_poll=2,
        preindex_missing=False,
    ):
        self.calls = []
        self.es_calls = 0
        self.drift_timeline = drift_timeline
        self.preexisting = preexisting
        self.wrong_media = wrong_media
        self.bad_retrieval = bad_retrieval
        self.bad_start = bad_start
        self.stop_status = stop_status
        self.reappear_after_cleanup = reappear_after_cleanup
        self.delivery_on_poll = delivery_on_poll
        self.preindex_missing = preindex_missing
        self.timeline_calls = 0
        self.caption_started = False
        self.caption_stopped = False
        self.delivery_polls = 0
        self.es_documents = 1 if preexisting else 0
        self.deleted = False
        self.absence_checks = 0

    def request(
        self, *, method, url, headers, body, timeout_seconds, max_response_bytes
    ):
        del headers, timeout_seconds, max_response_bytes
        parsed = urlsplit(url)
        self.calls.append((method, parsed.netloc, parsed.path, body))
        if parsed.netloc == "127.0.0.1:8000":
            return module.Response(
                200,
                encoded(
                    {
                        "schema_version": 1,
                        "catalog": "lvs-advertised-runtime-tools",
                        "expected": module.EXPECTED_TOOLS,
                        "available": module.EXPECTED_TOOLS,
                        "missing": [],
                        "ready": True,
                    }
                ),
            )
        if parsed.netloc == "127.0.0.1:8082":
            if parsed.path == "/vst/api/v1/storage/timelines":
                self.timeline_calls += 1
                value = timelines()
                if self.drift_timeline and self.timeline_calls == 2:
                    value["unrelated-sensor"][0]["endTime"] = (
                        "2026-08-02T09:01:01.000000Z"
                    )
                return module.Response(200, encoded(value))
            sensor = parsed.path.split("/")[-2]
            suffix = "a" if sensor == SENSOR_A else "b"
            return module.Response(
                200,
                encoded({"videoUrl": f"http://127.0.0.1:8080/media/{suffix}.mp4"}),
            )
        if parsed.netloc == "127.0.0.1:8080":
            value = MEDIA_A if parsed.path.endswith("a.mp4") else MEDIA_B
            if self.wrong_media and parsed.path.endswith("b.mp4"):
                value = b"wrong"
            return module.Response(200, value)
        if parsed.netloc == "127.0.0.1:9200":
            self.es_calls += 1
            if self.preindex_missing and self.es_calls == 1:
                return module.Response(
                    404,
                    encoded(
                        {
                            "error": {"type": "index_not_found_exception"},
                            "status": 404,
                        }
                    ),
                )
            if parsed.path.endswith("/_delete_by_query"):
                deleted = self.es_documents
                self.es_documents = 0
                self.deleted = True
                return module.Response(
                    200,
                    encoded(
                        {
                            "timed_out": False,
                            "deleted": deleted,
                            "version_conflicts": 0,
                            "failures": [],
                        }
                    ),
                )
            if self.caption_started and not self.caption_stopped:
                self.delivery_polls += 1
                if self.delivery_polls >= self.delivery_on_poll:
                    self.es_documents = max(self.es_documents, 3)
            if self.deleted:
                self.absence_checks += 1
                if self.reappear_after_cleanup and self.absence_checks >= 2:
                    self.es_documents = 1
            return module.Response(
                200,
                encoded(
                    {
                        "timed_out": False,
                        "_shards": {
                            "total": 1,
                            "successful": 1,
                            "skipped": 0,
                            "failed": 0,
                        },
                        "hits": {"total": {"value": self.es_documents}},
                    }
                ),
            )
        if parsed.netloc == "127.0.0.1:8018":
            assert method == "DELETE"
            assert parsed.path == f"/v1/generate_captions/{STREAM_ID}"
            self.caption_stopped = True
            return module.Response(self.stop_status, b"")
        if parsed.netloc == "127.0.0.1:8001":
            if parsed.path == "/v1/ready":
                return module.Response(200, b"")
            if parsed.path == "/v1/metadata":
                return module.Response(
                    200, encoded({"version": "3.0.0", "sub_version": "deadbeef"})
                )
            if parsed.path == "/models":
                return module.Response(200, encoded({"data": [{"id": MODEL}]}))
            if parsed.path == "/v1/generate_captions":
                value = json.loads(body)
                assert value["id"] == STREAM_ID
                assert value["override_vlm_prompt"] is True
                self.caption_started = True
                if self.bad_start:
                    return module.Response(500, encoded({"detail": "ambiguous"}))
                return module.Response(
                    200,
                    encoded({"id": STREAM_ID, "status": "accepted", "model": MODEL}),
                )
            if parsed.path == "/v1/stream_summarize":
                self.es_documents += 2
                if self.bad_retrieval:
                    return module.Response(
                        200,
                        encoded({"video_id": STREAM_ID, "model": MODEL, "choices": []}),
                    )
                return module.Response(
                    200,
                    encoded(
                        {
                            "video_id": STREAM_ID,
                            "model": MODEL,
                            "choices": [
                                {
                                    "message": {
                                        "content": "Observed a vehicle crossing in the owned live caption."
                                    }
                                }
                            ],
                        }
                    ),
                )
        raise AssertionError((method, url))


def test_plan_is_inert_and_preserves_frozen_bound():
    result = module.compile_plan()
    assert result["status"] == "inert_plan_valid"
    assert result["runtime_activity_performed"] is False
    assert result["max_requests"] == 24
    assert result["frozen_canonical_max_requests"] == 14
    assert result["executor_ready"] is False


def test_authorization_rejected_before_transport():
    transport = FakeTransport()
    with pytest.raises(module.ExecutorError, match="authorization_required"):
        module.execute(
            manifest=manifest(), acknowledgement="wrong", transport=transport
        )
    assert transport.calls == []


def test_live_stream_uuid_is_deterministically_run_owned():
    value = manifest()
    value["live_stream"]["id"] = "33333333-3333-4333-8333-333333333333"
    with pytest.raises(module.ExecutorError, match="invalid_manifest"):
        module.execute(
            manifest=value,
            acknowledgement=ACK,
            transport=FakeTransport(),
            sleeper=lambda _seconds: None,
        )


def test_closure_success_exact_readback_delivery_retrieval_and_state():
    transport = FakeTransport()
    result = module.execute(
        manifest=manifest(),
        acknowledgement=ACK,
        transport=transport,
        sleeper=lambda _seconds: None,
    )
    assert result["status"] == "closure_supplement_complete_non_promoting"
    assert result["budget"]["requests"] == 21
    assert len(result["fixture_readback"]) == 2
    assert all(row["exact_bytes_readback"] for row in result["fixture_readback"])
    assert result["live_caption"] == {
        "stream_id_sha256": module._sha(STREAM_ID),
        "preexisting_collection_empty": True,
        "generation_accepted": True,
        "logstash_delivery_observed": True,
        "ca_rag_retrieval_nonempty": True,
        "poll_attempts": 2,
    }
    assert result["state_preservation"]["complete_vst_timeline_preserved"] is True
    assert result["cleanup"] == {
        "stop_acknowledged": True,
        "delivery_quiescent": True,
        "quiescence_observations": 2,
        "deleted_documents": 5,
        "owned_collection_absent": True,
        "delayed_no_reappearance": True,
    }
    assert transport.caption_stopped is True
    assert result["promotion_eligible"] is False
    assert result["executor_ready"] is False


@pytest.mark.parametrize(
    "content",
    [
        "No events found for vehicle crossing.",
        "",
    ],
)
def test_ca_rag_nonempty_oracle_rejects_empty_or_negative_content(content):
    value = {
        "video_id": STREAM_ID,
        "model": MODEL,
        "choices": [{"message": {"content": content}}],
    }
    assert module._nonempty_completion(value, STREAM_ID, MODEL) is False


def test_ca_rag_nonempty_oracle_does_not_claim_semantic_correlation():
    value = {
        "video_id": STREAM_ID,
        "model": MODEL,
        "choices": [{"message": {"content": "Observed owned live caption."}}],
    }
    assert module._nonempty_completion(value, STREAM_ID, MODEL) is True


def test_main_deadline_preserves_cleanup_reserve():
    now = [0.0]

    class DeadlineTransport(FakeTransport):
        def request(self, **kwargs):
            response = super().request(**kwargs)
            if urlsplit(kwargs["url"]).path == "/v1/generate_captions":
                now[0] = 1501.0
            return response

    transport = DeadlineTransport()
    with pytest.raises(module.ExecutorError, match="oracle_failed"):
        module.execute(
            manifest=manifest(),
            acknowledgement=ACK,
            transport=transport,
            sleeper=lambda _seconds: None,
            clock=lambda: now[0],
        )
    assert transport.caption_stopped is True
    assert transport.deleted is True


@pytest.mark.parametrize(
    "value",
    [
        {
            "timed_out": True,
            "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
            "hits": {"total": {"value": 0}},
        },
        {
            "timed_out": False,
            "_shards": {"total": 1, "successful": 0, "skipped": 0, "failed": 1},
            "hits": {"total": {"value": 0}},
        },
        {"timed_out": False, "hits": {"total": {"value": 0}}},
    ],
)
def test_es_total_rejects_timed_out_partial_or_unattributed_search(value):
    with pytest.raises(module.ExecutorError, match="invalid_response"):
        module._es_total(value)


def test_absent_owned_index_is_valid_empty_prestate():
    result = module.execute(
        manifest=manifest(),
        acknowledgement=ACK,
        transport=FakeTransport(preindex_missing=True),
        sleeper=lambda _seconds: None,
    )
    assert result["live_caption"]["preexisting_collection_empty"] is True


@pytest.mark.parametrize(
    "transport",
    [
        FakeTransport(preexisting=True),
        FakeTransport(wrong_media=True),
        FakeTransport(drift_timeline=True),
    ],
)
def test_fail_closed_on_preexisting_range_media_drift_or_state_drift(transport):
    with pytest.raises(module.ExecutorError, match="oracle_failed"):
        module.execute(
            manifest=manifest(),
            acknowledgement=ACK,
            transport=transport,
            sleeper=lambda _seconds: None,
        )


def test_manifest_requires_owned_unique_fixture_and_stream_identity():
    value = manifest()
    value["fixtures"][1]["sensor_id"] = value["fixtures"][0]["sensor_id"]
    with pytest.raises(module.ExecutorError, match="invalid_manifest"):
        module.execute(
            manifest=value,
            acknowledgement=ACK,
            transport=FakeTransport(),
            sleeper=lambda _seconds: None,
        )


def test_media_url_must_be_explicitly_allowed_numeric_loopback():
    value = manifest()
    value["allowed_media_origins"] = ["http://127.0.0.1:9999"]
    with pytest.raises(module.ExecutorError, match="oracle_failed"):
        module.execute(
            manifest=value,
            acknowledgement=ACK,
            transport=FakeTransport(),
            sleeper=lambda _seconds: None,
        )


def test_failure_after_start_still_stops_and_cleans_exact_owned_collection():
    transport = FakeTransport(bad_retrieval=True)
    with pytest.raises(module.ExecutorError, match="oracle_failed"):
        module.execute(
            manifest=manifest(),
            acknowledgement=ACK,
            transport=transport,
            sleeper=lambda _seconds: None,
        )
    assert transport.caption_stopped is True
    assert transport.deleted is True
    assert transport.es_documents == 0


def test_ambiguous_start_response_still_stops_and_cleans():
    transport = FakeTransport(bad_start=True)
    with pytest.raises(module.ExecutorError, match="oracle_failed"):
        module.execute(
            manifest=manifest(),
            acknowledgement=ACK,
            transport=transport,
            sleeper=lambda _seconds: None,
        )
    assert transport.caption_stopped is True
    assert transport.deleted is True
    assert transport.es_documents == 0


def test_stop_failure_does_not_skip_database_cleanup_and_fails_closed():
    transport = FakeTransport(stop_status=500)
    with pytest.raises(module.ExecutorError, match="cleanup_failed"):
        module.execute(
            manifest=manifest(),
            acknowledgement=ACK,
            transport=transport,
            sleeper=lambda _seconds: None,
        )
    assert transport.deleted is True
    assert transport.es_documents == 0


def test_delayed_reappearance_fails_cleanup_closed():
    transport = FakeTransport(reappear_after_cleanup=True)
    with pytest.raises(module.ExecutorError, match="cleanup_failed"):
        module.execute(
            manifest=manifest(),
            acknowledgement=ACK,
            transport=transport,
            sleeper=lambda _seconds: None,
        )


def test_last_allowed_delivery_poll_completes_within_exact_budget():
    transport = FakeTransport(delivery_on_poll=5)
    sleeps = []
    result = module.execute(
        manifest=manifest(),
        acknowledgement=ACK,
        transport=transport,
        sleeper=sleeps.append,
    )
    assert result["live_caption"]["poll_attempts"] == 5
    assert result["budget"]["requests"] == 24
    assert sleeps == [2.0] * 6
