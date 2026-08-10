from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]
SPEC = importlib.util.spec_from_file_location("vios_replay_verify", HERE / "verify.py")
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def load(name: str):
    return json.loads((HERE / name).read_text())


def test_validator_scope_fix_is_method_specific() -> None:
    header = (
        REPO / "services/vios/src/framework/web/validators/SchemaValidator.h"
    ).read_text()
    implementation = (
        REPO / "services/vios/src/framework/web/validators/SchemaValidator.cpp"
    ).read_text()
    handler = (
        REPO
        / "services/vios/src/framework/web/http_server/HttpServerRequestHandler.cpp"
    ).read_text()
    spec = (
        REPO
        / "services/vios/src/framework/web/api_spec/services/replay_stream_spec.h"
    ).read_text()
    assert "enum class RequestValidationScope" in header
    assert "QueryOnly" in header
    assert "RequestValidationScope::BodyAndQuery" in implementation
    assert "RequestValidationScope::QueryOnly" in handler
    assert spec.count('{"mediaSessionId", JsonType::String, true, Format::NOT_EMPTY}') >= 2
    assert spec.count('{"peerId", JsonType::String, true, Format::NOT_EMPTY}') >= 2


def test_ingress_shim_is_exact_get_only_compatibility() -> None:
    config = (REPO / "deploy/docker/services/vios/configs/nginx-vst-direct.conf").read_text()
    assert "location = /vst/api/v1/replay/stream/seek" in config
    assert 'if ($request_method = GET)' in config
    assert 'set $args "${args}&action=seekForward";' in config


def test_retained_runtime_receipt_is_bounded_and_private() -> None:
    raw = (HERE / "runtime-receipt.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == VERIFY.EXPECTED["receipt"]
    receipt = json.loads(raw)
    assert receipt["status"] == "passed"
    assert receipt["observations"]["semantic_result"]["decoded_frames_after_seek"] == 50
    assert receipt["observations"]["wire_contract"]["invalid_action_status"] == 501
    assert receipt["cleanup"]["result"] == "passed"
    for forbidden in (b'"peerId":', b'"mediaSessionId":', b'"sdp":', b'"candidate":'):
        assert forbidden not in raw


def test_official_projection_is_fail_closed() -> None:
    result = VERIFY.verify()
    assert result["status"] == "passed"
    assert result["capability_id"] == "protocol.vios.webrtc-replay"
    assert result["official_capability_count"] == 289
