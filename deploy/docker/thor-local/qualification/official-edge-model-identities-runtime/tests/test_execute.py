from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "official_edge_model_identities_execute", PACKAGE / "execute.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


LLM_ID = "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8"
VLM_ID = "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
LLM_IMAGE = (
    "sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8"
)
VLM_IMAGE = (
    "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504"
)
REVISION = "3fe6dab75665a93884214ad4b1b95cf02717d081"


class FakeResponse:
    def __init__(self, url: str, body: bytes) -> None:
        self.status = 200
        self.headers = {"Content-Type": "application/json"}
        self._url = url
        self._body = body

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def close(self) -> None:
        return None


class FakeOpener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = [executor._canonical_bytes(row) for row in responses]
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> FakeResponse:
        assert timeout == 45.0
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected request")
        return FakeResponse(request.full_url, self.responses.pop(0))


def _documents() -> dict[str, dict[str, Any]]:
    contract = executor._load_contract()
    snapshot = Path("/tmp/models--nvidia--NVIDIA-Nemotron-3-Nano-4B-FP8")
    return {
        "vss-nemotron-edge-4b": {
            "Id": "a" * 64,
            "Name": "/vss-nemotron-edge-4b",
            "Image": LLM_IMAGE,
            "RestartCount": 0,
            "State": {
                "Running": True,
                "OOMKilled": False,
                "StartedAt": "2026-08-10T12:00:00Z",
                "Health": {"Status": "healthy"},
            },
            "Config": {
                "Image": contract["models"]["llm"]["image_reference"],
                "Cmd": contract["models"]["llm"]["command"],
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(snapshot / "snapshots" / REVISION),
                    "Destination": "/models/edge4b",
                    "RW": False,
                },
                {
                    "Type": "bind",
                    "Source": str(snapshot / "blobs"),
                    "Destination": "/blobs",
                    "RW": False,
                },
            ],
        },
        "vss-rtvi-vlm": {
            "Id": "b" * 64,
            "Name": "/vss-rtvi-vlm",
            "Image": VLM_IMAGE,
            "RestartCount": 0,
            "State": {
                "Running": True,
                "OOMKilled": False,
                "StartedAt": "2026-08-10T12:00:01Z",
                "Health": {"Status": "healthy"},
            },
            "Config": {
                "Image": contract["models"]["vlm"]["image_reference"],
                "Env": [
                    "MODEL_PATH=ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final",
                    "VLM_MODEL_TO_USE=cosmos-reason3",
                    "NUM_GPUS=1",
                    "VLM_BATCH_SIZE=1",
                    "NGC_API_KEY=",
                    "VIA_VLM_API_KEY=",
                ],
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/tmp/ngc-model-cache",
                    "Destination": "/opt/nvidia/rtvi/.rtvi/ngc_model_cache",
                    "RW": True,
                }
            ],
        },
    }


def _responses(
    *, vlm_answer: str = "red, green, blue, yellow", asset_post: int = 0
) -> dict[str, list[dict[str, Any]]]:
    return {
        "llm": [
            {"data": [{"id": LLM_ID}]},
            {
                "model": LLM_ID,
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "thor_contract_ping",
                                        "arguments": json.dumps(
                                            {
                                                "message": "THOR_OFFICIAL_EDGE_MODEL_OK"
                                            }
                                        ),
                                    }
                                }
                            ],
                        }
                    }
                ],
            },
        ],
        "vlm": [
            {"data": [{"id": VLM_ID}]},
            {"asset_count": 0, "asset_count_with_storage": 0},
            {
                "model": VLM_ID,
                "choices": [{"message": {"content": vlm_answer}}],
            },
            {"asset_count": asset_post, "asset_count_with_storage": 0},
        ],
    }


def _run(
    *,
    responses: dict[str, list[dict[str, Any]]] | None = None,
    inspector: Any = None,
) -> tuple[dict[str, Any], dict[str, FakeOpener]]:
    documents = _documents()
    openers = {
        role: FakeOpener(rows)
        for role, rows in (responses or _responses()).items()
    }

    def inspect(name: str) -> dict[str, Any]:
        return copy.deepcopy(documents[name])

    receipt = executor.execute(
        acknowledgement=executor.ACKNOWLEDGEMENT,
        inspector=inspector or inspect,
        readiness_runner=lambda _edge, _cosmos, _timeout: {
            "passed": True,
            "duration_seconds": 1.0,
            "stdout_sha256": executor._sha256_bytes(executor.READINESS_STDOUT),
        },
        opener_factory=lambda role: openers[role],
        free_bytes_provider=lambda: 20 * 1024**3,
        monotonic=iter([0.0, 2.5]).__next__,
    )
    return receipt, openers


def test_plan_is_inert_and_source_locked() -> None:
    result = executor.plan()
    assert result["status"] == "passed"
    assert result["runtime_activity_performed"] is False
    assert result["http_request_count"] == 0
    assert result["writes_or_lifecycle_actions"] is False


def test_acknowledgement_is_required_before_host_inspection() -> None:
    called = False

    def inspect(_name: str) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError

    with pytest.raises(executor.QualificationError) as error:
        executor.execute(acknowledgement="wrong", inspector=inspect)
    assert error.value.code == "acknowledgement_required"
    assert called is False


def test_exact_models_pass_semantic_probes_without_mutation() -> None:
    receipt, openers = _run()
    assert receipt["status"] == "passed"
    assert receipt["http_request_count"] == 6
    assert receipt["semantic_action_count"] == 2
    assert receipt["llm_proof"]["tool_arguments_exact"] is True
    assert receipt["vlm_proof"]["visual_answer_exact"] is True
    assert receipt["cleanup"]["mutation"] == "none"
    assert receipt["cleanup"]["asset_statistics_exact"] is True
    assert receipt["runtime_identity"]["pre"] == receipt["runtime_identity"]["post"]
    assert len(openers["llm"].requests) == 2
    assert len(openers["vlm"].requests) == 4
    assert all(
        request.full_url.startswith("http://127.0.0.1:")
        for opener in openers.values()
        for request in opener.requests
    )
    assert all(
        "Authorization" not in request.headers
        for opener in openers.values()
        for request in opener.requests
    )


def test_wrong_vlm_answer_fails_closed() -> None:
    with pytest.raises(executor.QualificationError) as error:
        _run(responses=_responses(vlm_answer="yellow, blue, green, red"))
    assert error.value.code == "invalid_response"


def test_asset_state_change_fails_closed() -> None:
    with pytest.raises(executor.QualificationError) as error:
        _run(responses=_responses(asset_post=1))
    assert error.value.code == "runtime_state_changed"


def test_container_restart_between_pre_and_post_fails_closed() -> None:
    documents = _documents()
    calls = 0

    def inspect(name: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        document = copy.deepcopy(documents[name])
        if calls > 2 and name == "vss-rtvi-vlm":
            document["RestartCount"] = 1
        return document

    with pytest.raises(executor.QualificationError) as error:
        _run(inspector=inspect)
    assert error.value.code == "identity_mismatch"


def test_non_loopback_target_is_rejected() -> None:
    with pytest.raises(executor.QualificationError) as error:
        executor._validate_origin("http://192.0.2.10:8018")
    assert error.value.code == "configuration_error"


def test_png_fixture_hashes_match_the_contract() -> None:
    contract = executor._load_contract()
    _payload, digest = executor._vlm_payload(contract)
    assert digest == contract["semantic_contract"]["vlm_composite_image"]["sha256"]


def test_receipt_validator_rejects_retained_raw_prompt() -> None:
    receipt, _openers = _run()
    receipt["unsafe"] = "Call the thor_contract_ping tool"
    with pytest.raises(executor.QualificationError) as error:
        executor.validate_receipt(receipt)
    assert error.value.code == "configuration_error"
