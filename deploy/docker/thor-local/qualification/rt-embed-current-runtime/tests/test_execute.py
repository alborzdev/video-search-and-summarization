from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys
from typing import Any

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rt_embed_current_runtime_execute", PACKAGE / "execute.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


class FakeResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return b"{}"


class FakeOpener:
    def __init__(self) -> None:
        self.calls = 0

    def open(self, _request: object, timeout: float) -> FakeResponse:
        assert timeout == 90
        self.calls += 1
        return FakeResponse()


def _runtime() -> tuple[dict[str, Any], Any]:
    contract, raw = executor._load_contract()
    return contract, executor.Runtime(copy.deepcopy(contract), executor._sha256(raw))


def test_contract_is_source_locked_and_default_execution_is_disabled() -> None:
    contract, raw = executor._load_contract()
    assert executor._sha256(raw) == executor.EXPECTED_CONTRACT_SHA256
    assert contract["default_execution_enabled"] is False
    assert contract["acknowledgement"] == executor.ACKNOWLEDGEMENT
    assert contract["execution_bounds"]["external_network"] == "forbidden"
    assert contract["execution_bounds"]["image_pull"] == "forbidden"
    assert contract["execution_bounds"]["model_staging"] == "forbidden"
    assert contract["execution_bounds"]["service_lifecycle"] == "forbidden"


def test_strict_json_rejects_duplicate_keys() -> None:
    with pytest.raises(executor.QualificationError) as error:
        executor._strict_json(b'{"status":"passed","status":"failed"}')
    assert error.value.code == "configuration_error"


def test_non_loopback_service_origin_is_rejected() -> None:
    contract, raw = executor._load_contract()
    contract["service"]["origin"] = "http://192.0.2.20:8017"
    with pytest.raises(executor.QualificationError) as error:
        executor.Runtime(contract, executor._sha256(raw))
    assert error.value.code == "configuration_error"


def test_http_budget_includes_unretained_cleanup_requests() -> None:
    contract, runtime = _runtime()
    contract["execution_bounds"]["max_http_requests"] = 1
    runtime.bounds = contract["execution_bounds"]
    opener = FakeOpener()
    runtime.opener = opener
    status, value = runtime.json_request(
        "GET", "/v1/ready", action_id="cleanup-probe", record=False
    )
    assert status == 200
    assert value == {}
    assert runtime.http_requests == 1
    assert runtime.observations == []
    with pytest.raises(executor.QualificationError) as error:
        runtime.json_request(
            "GET", "/v1/live", action_id="cleanup-probe-two", record=False
        )
    assert error.value.code == "budget_exceeded"
    assert opener.calls == 1


def test_best_effort_cleanup_covers_every_owned_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, runtime = _runtime()
    resources = contract["owned_resources"]
    runtime.owned_file_ids = {
        resources["file_id"],
        resources["data_url_id"],
        resources["denied_file_url_id"],
    }
    runtime.owned_stream_ids = {
        resources["single_stream_id"],
        *resources["batch_stream_ids"],
    }
    runtime.camera_owned = True
    requests: list[tuple[str, str]] = []

    def request(method: str, path: str, **_kwargs: object) -> tuple[int, bytes, None]:
        requests.append((method, path))
        return 200, b"", None

    def json_request(
        method: str, path: str, **_kwargs: object
    ) -> tuple[int, dict[str, Any]]:
        requests.append((method, path))
        return 200, {}

    monkeypatch.setattr(runtime, "request", request)
    monkeypatch.setattr(runtime, "json_request", json_request)
    monkeypatch.setattr(runtime, "stop_publisher", lambda: None)
    monkeypatch.setattr(runtime, "stop_mediamtx", lambda: None)
    monkeypatch.setattr(runtime, "_stop_container", lambda _name: None)
    runtime.cleanup_resources()

    assert {
        path.removeprefix("/v1/generate_video_embeddings/")
        for method, path in requests
        if method == "DELETE" and path.startswith("/v1/generate_video_embeddings/")
    } == runtime.owned_stream_ids | {
        resources["single_stream_id"],
        *resources["batch_stream_ids"],
    }
    assert sum(path == "/v1/stream/remove" for _method, path in requests) == 1
    assert {
        path.removeprefix("/v1/files/")
        for method, path in requests
        if method == "DELETE" and path.startswith("/v1/files/")
    } == {
        resources["file_id"],
        resources["data_url_id"],
        resources["denied_file_url_id"],
    }
    assert runtime.owned_file_ids == set()
    assert runtime.owned_stream_ids == set()
    assert runtime.camera_owned is False
    assert runtime.cleanup_failures == []


def test_vectors_require_exact_dimension_and_finite_numbers() -> None:
    assert executor._validate_vector([0.0] * 768, 768) == [0.0] * 768
    for value in ([0.0] * 767, [0.0] * 767 + [float("nan")], "not-a-vector"):
        with pytest.raises(executor.QualificationError) as error:
            executor._validate_vector(value, 768)
        assert error.value.code == "embedding_contract_failed"
