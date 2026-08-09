from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "official_edge_semantic_executor", HERE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
EXECUTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXECUTOR)

TOKEN = "fake-authorization-token"
NOW = datetime(2026, 8, 2, 15, 0, tzinfo=timezone.utc)
POSITIVE = "BLUE_TRIANGLE_271"
ABSENT = "ORANGE_CIRCLE_992"


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class Response:
    def __init__(
        self,
        url: str,
        body: bytes,
        media_type: str = "application/json",
        *,
        status: int = 200,
        final_url: str | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.final_url = final_url or url
        self.headers = {
            "Content-Type": media_type,
            "Content-Length": str(len(body)),
        }
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def geturl(self) -> str:
        return self.final_url

    def close(self) -> None:
        self.closed = True


class QueueOpener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self, bodies: list[tuple[bytes, str]]) -> None:
        self.bodies = list(bodies)
        self.requests: list[object] = []
        self.redirect_at: int | None = None

    def open(self, request: object, timeout: float) -> Response:
        index = len(self.requests)
        self.requests.append(request)
        body, media_type = self.bodies.pop(0)
        url = request.full_url  # type: ignore[attr-defined]
        final = "http://127.0.0.1:9/redirected" if self.redirect_at == index else url
        return Response(url, body, media_type, final_url=final)


def model(model_id: str) -> bytes:
    return encoded({"data": [{"id": model_id}]})


def message(content: str, **extra: object) -> bytes:
    return encoded({"choices": [{"message": {"content": content, **extra}}]})


def successful_openers() -> dict[str, QueueOpener]:
    return {
        "llm": QueueOpener(
            [
                (model("nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8"), "application/json"),
                (
                    message(
                        "",
                        tool_calls=[
                            {
                                "function": {
                                    "name": "thor_contract_echo",
                                    "arguments": json.dumps(
                                        {"value": "thor-tool-fake-run-1"}
                                    ),
                                }
                            }
                        ],
                    ),
                    "application/json",
                ),
                (message("THOR_NO_TOOL_TARGET"), "application/json"),
            ]
        ),
        "vlm": QueueOpener(
            [
                (
                    model("nim_nvidia_cosmos3-nano-reasoner_bf16-final"),
                    "application/json",
                ),
                (message(POSITIVE), "application/json"),
                (message("THOR_VISUAL_ABSENT"), "application/json"),
            ]
        ),
        "agent": QueueOpener(
            [
                (
                    f"data: {POSITIVE} THOR_AGENT_BOTH_MODELS\n\n".encode(),
                    "text/event-stream",
                )
            ]
        ),
    }


def readiness_receipt() -> dict[str, object]:
    contract = json.loads((HERE / "contract.json").read_text())
    projected = {
        row["path"]: row["sha256"]
        for row in contract["source_locks"]
        if row["path"]
        in {
            "deploy/docker/thor-local/official-edge/contract.json",
            "deploy/docker/thor-local/official-edge/artifacts.lock.json",
        }
    }
    return {
        "schema_version": 1,
        "plan_id": "vss-3.2.1-thor-official-edge-readiness",
        "captured_at_utc": NOW.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "inspection_mode": "read_only_host",
        "qualification_state": "prelaunch_ready_not_runtime_qualified",
        "runtime_qualification_performed": False,
        "source_locks": {
            "state": "match",
            "files": [
                {
                    "path": path,
                    "expected_sha256": digest,
                    "actual_sha256": digest,
                    "state": "match",
                }
                for path, digest in projected.items()
            ],
        },
        "artifact_lock": {
            "lock_state": "complete_exact",
            "entries": {
                "edge_snapshot": {"state": "locked_exact", "tree_present": True},
                "cosmos_cache": {"state": "locked_exact", "tree_present": True},
            },
        },
        "artifacts": {
            "edge_snapshot": {"state": "candidate_present_unlocked"},
            "cosmos_cache": {"state": "candidate_present_unlocked"},
            "exact_tree_verification": {"state": "exact_match"},
        },
        "images": {
            "edge_vllm": {
                "state": "present_exact",
                "reference": "ghcr.io/nvidia-ai-iot/vllm@sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8",
                "image_id": "sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8",
                "contract_lock": {"state": "locked_exact"},
            },
            "rt_vlm": {
                "state": "present_exact",
                "reference": "nvcr.io/nvidia/vss-core/vss-rt-vlm@sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504",
                "image_id": "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504",
                "contract_lock": {"state": "locked_exact"},
            },
        },
        "memory": {"state": "pass"},
        "disk": {
            "state": "pass_no_additional_staging_required",
            "capacity_qualified": True,
            "required_additional_bytes": 0,
        },
        "containers": {
            "vss-nemotron-edge-4b": {
                "state": "running",
                "required_image_reference_matches": True,
            },
            "vss-rtvi-vlm": {
                "state": "running",
                "required_image_reference_matches": True,
            },
            "vss-agent": {"state": "running"},
        },
        "blockers": [],
    }


class Fixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.prerequisite = root / "readiness.json"
        self.media = root / "visual.png"
        self.manifest = root / "manifest.json"
        prereq_raw = encoded(readiness_receipt())
        self.prerequisite.write_bytes(prereq_raw)
        media_raw = b"fake inert visual bytes " + POSITIVE.encode()
        self.media.write_bytes(media_raw)
        self.value = {
            "schema_version": 1,
            "package_id": "thor-official-edge-semantic-runtime-evidence-successor-v1",
            "run_id": "fake-run-1",
            "authorization": {
                "authorization_id": "fake-auth-1",
                "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
            },
            "prerequisite": {
                "receipt_path": str(self.prerequisite),
                "receipt_sha256": hashlib.sha256(prereq_raw).hexdigest(),
            },
            "origins": {
                "llm": "http://127.0.0.1:30081",
                "vlm": "http://127.0.0.1:8018",
                "agent": "http://127.0.0.1:8000",
            },
            "media": {
                "path": str(self.media),
                "sha256": hashlib.sha256(media_raw).hexdigest(),
                "byte_count": len(media_raw),
                "media_type": "image/png",
            },
            "visual_oracle": {
                "positive_literal": POSITIVE,
                "absent_literal": ABSENT,
            },
        }
        self.write()

    def write(self) -> None:
        self.manifest.write_text(json.dumps(self.value), encoding="utf-8")

    def close(self) -> None:
        self.temp.cleanup()


class ExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()
        self.openers = successful_openers()

    def tearDown(self) -> None:
        self.fixture.close()

    def run_success(self, **kwargs: object) -> dict[str, object]:
        return EXECUTOR.execute(
            self.fixture.manifest,
            acknowledgement=EXECUTOR.ACKNOWLEDGEMENT,
            authorization_token=TOKEN,
            opener_factory=lambda role: self.openers[role],
            now=lambda: NOW,
            **kwargs,
        )

    def assert_code(self, code: str, callback: object) -> None:
        with self.assertRaises(EXECUTOR.CollectorError) as caught:
            callback()  # type: ignore[operator]
        self.assertEqual(caught.exception.code, code)

    def test_default_plan_is_inert(self) -> None:
        with mock.patch.object(EXECUTOR, "LiveOpener", side_effect=AssertionError):
            result = EXECUTOR.plan()
        self.assertFalse(result["runtime_activity_performed"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["warehouse_sample_bundle"], "excluded")

    def test_acknowledgement_is_required_before_manifest_read_or_opener(self) -> None:
        missing = Path(self.fixture.temp.name) / "missing.json"
        self.assert_code(
            "acknowledgement_required",
            lambda: EXECUTOR.execute(
                missing, acknowledgement="no", authorization_token=TOKEN
            ),
        )

    def test_success_is_exact_non_promoting_and_sanitized(self) -> None:
        receipt = self.run_success()
        self.assertEqual(receipt["status"], "passed_candidate_non_promoting")
        self.assertFalse(receipt["promotion_eligible"])
        self.assertEqual(receipt["budget"]["requests"], 7)
        self.assertEqual(receipt["budget"]["actions"], 9)
        self.assertEqual(len(receipt["observations"]), 7)
        serialized = json.dumps(receipt)
        for raw in (
            TOKEN,
            str(self.fixture.media),
            str(self.fixture.prerequisite),
            POSITIVE,
            ABSENT,
        ):
            self.assertNotIn(raw, serialized)

    def test_per_run_tool_challenge_is_explicit_and_hash_bound(self) -> None:
        receipt = self.run_success()
        challenge = "thor-tool-fake-run-1"
        request = self.openers["llm"].requests[1]
        self.assertIn(challenge, request.data.decode("utf-8"))
        self.assertEqual(
            receipt["identity"]["llm_tool_challenge_sha256"],
            hashlib.sha256(challenge.encode()).hexdigest(),
        )
        self.assertNotIn(challenge, json.dumps(receipt))

    def test_positive_visual_oracle_is_hidden_from_prompt(self) -> None:
        self.run_success()
        positive_request = self.openers["vlm"].requests[1]
        prompt = positive_request.data.decode("utf-8")
        self.assertNotIn(POSITIVE, prompt)
        self.assertNotIn(ABSENT, prompt)

    def test_manifest_cannot_supply_prerequisite_capture_time(self) -> None:
        self.fixture.value["prerequisite"]["captured_at_utc"] = (
            "2026-08-02T15:00:00.000000Z"
        )
        self.fixture.write()
        self.assert_code("invalid_manifest", self.run_success)

    def test_file_mtime_cannot_replace_hash_bound_capture_time(self) -> None:
        old = (NOW - timedelta(days=30)).timestamp()
        os.utime(self.fixture.prerequisite, (old, old))
        receipt = self.run_success()
        self.assertEqual(receipt["prerequisite"]["age_seconds"], 0)

    def test_wrong_llm_and_vlm_ids_are_rejected(self) -> None:
        self.openers["llm"].bodies[0] = (model("wrong-id"), "application/json")
        self.assert_code("identity_mismatch", self.run_success)
        self.openers = successful_openers()
        self.openers["vlm"].bodies[0] = (model("alias"), "application/json")
        self.assert_code("identity_mismatch", self.run_success)

    def test_hostname_alias_and_cloud_origins_are_rejected(self) -> None:
        self.fixture.value["origins"]["llm"] = "http://localhost:30081"
        self.fixture.write()
        self.assert_code("invalid_manifest", self.run_success)
        self.fixture.value["origins"]["llm"] = "https://api.nvidia.com:443"
        self.fixture.write()
        self.assert_code("invalid_manifest", self.run_success)

    def test_missing_and_stale_prerequisite_are_rejected(self) -> None:
        self.fixture.prerequisite.unlink()
        self.assert_code("invalid_prerequisite", self.run_success)
        self.fixture.close()
        self.fixture = Fixture()
        value = readiness_receipt()
        value["captured_at_utc"] = (
            (NOW - timedelta(seconds=901))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        raw = encoded(value)
        self.fixture.prerequisite.write_bytes(raw)
        self.fixture.value["prerequisite"]["receipt_sha256"] = hashlib.sha256(
            raw
        ).hexdigest()
        self.fixture.write()
        self.assert_code("stale_prerequisite", self.run_success)

    def test_wrong_prerequisite_identity_and_source_projection_are_rejected(
        self,
    ) -> None:
        value = readiness_receipt()
        value["containers"]["vss-rtvi-vlm"]["state"] = "missing"
        raw = encoded(value)
        self.fixture.prerequisite.write_bytes(raw)
        self.fixture.value["prerequisite"]["receipt_sha256"] = hashlib.sha256(
            raw
        ).hexdigest()
        self.fixture.write()
        self.assert_code("invalid_prerequisite", self.run_success)

    def test_cloud_key_and_qwen_fallback_are_rejected(self) -> None:
        contract = EXECUTOR._contract()
        locked = EXECUTOR._verify_source_locks(contract)
        env_key = "deploy/docker/thor-local/official-edge/official-edge.env"
        cloud = dict(locked)
        cloud[env_key] += b"\nNVIDIA_API_KEY=secret\n"
        self.assert_code(
            "identity_mismatch", lambda: EXECUTOR._validate_no_cloud(contract, cloud)
        )
        qwen = dict(locked)
        qwen[env_key] += b"\nQwen/Qwen3-VL-8B-Instruct-FP8\n"
        self.assert_code(
            "configuration_error", lambda: EXECUTOR._validate_no_cloud(contract, qwen)
        )

    def test_tool_and_visual_false_positives_are_rejected(self) -> None:
        self.openers["llm"].bodies[1] = (
            message("thor-tool-positive without a tool"),
            "application/json",
        )
        self.assert_code("invalid_response", self.run_success)
        self.openers = successful_openers()
        self.openers["vlm"].bodies[1] = (
            message(POSITIVE + " " + ABSENT),
            "application/json",
        )
        self.assert_code("invalid_response", self.run_success)

    def test_agent_must_prove_both_models_in_one_workflow(self) -> None:
        self.openers["agent"].bodies[0] = (POSITIVE.encode(), "text/event-stream")
        self.assert_code("invalid_response", self.run_success)

    def test_redirect_and_proxy_enabled_opener_are_rejected(self) -> None:
        self.openers["llm"].redirect_at = 0
        self.assert_code("transport_error", self.run_success)
        self.openers = successful_openers()
        self.openers["llm"].proxies_enabled = True
        self.assert_code("configuration_error", self.run_success)

    def test_duration_budget_leaves_cleanup_reserve(self) -> None:
        ticks = iter([0.0, 106.0])
        self.assert_code(
            "budget_exceeded", lambda: self.run_success(monotonic=lambda: next(ticks))
        )

    def test_cleanup_postcondition_is_mandatory(self) -> None:
        self.assert_code(
            "cleanup_failed", lambda: self.run_success(cleanup_probe=lambda: False)
        )

    def test_receipt_digest_and_content_tamper_are_rejected(self) -> None:
        receipt = self.run_success()
        path = Path(self.fixture.temp.name) / "receipt.json"
        raw = encoded(receipt)
        path.write_bytes(raw)
        EXECUTOR.validate_receipt_file(path, hashlib.sha256(raw).hexdigest())
        self.assert_code(
            "invalid_receipt", lambda: EXECUTOR.validate_receipt_file(path, "0" * 64)
        )
        tampered = copy.deepcopy(receipt)
        tampered["observations"][0]["observation_id"] = "vlm-model-identity"
        self.assert_code(
            "invalid_receipt", lambda: EXECUTOR.validate_receipt_document(tampered)
        )
        tampered = copy.deepcopy(receipt)
        tampered["collector_locks"]["contract_schema_sha256"] = "0" * 64
        self.assert_code(
            "invalid_receipt", lambda: EXECUTOR.validate_receipt_document(tampered)
        )


if __name__ == "__main__":
    unittest.main()
