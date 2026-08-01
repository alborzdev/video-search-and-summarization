from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest


HERE = Path(__file__).resolve()
LANE_DIR = HERE.parents[1]
QUALIFIER_PATH = LANE_DIR / "qualify.py"
SPEC = importlib.util.spec_from_file_location(
    "local_alternate_qualifier", QUALIFIER_PATH
)
assert SPEC is not None and SPEC.loader is not None
qualifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qualifier
SPEC.loader.exec_module(qualifier)


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def response(value: object, status: int = 200) -> Any:
    return qualifier.HttpResult(
        status, "application/json; charset=utf-8", encoded(value)
    )


class FakeTransport:
    def __init__(self, results: list[Any]) -> None:
        self.results = list(results)
        self.requests_attempted = 0
        self.requests: list[tuple[str, str, str, bytes]] = []

    def request(self, endpoint: str, method: str, path: str, body: bytes) -> Any:
        if self.requests_attempted >= qualifier.MAX_REQUESTS:
            raise AssertionError("qualifier attempted more than four requests")
        self.requests_attempted += 1
        self.requests.append((endpoint, method, path, body))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def successful_results() -> list[Any]:
    return [
        response({"object": "list", "data": [{"id": "datasheet-chat"}]}),
        response({"object": "list", "data": [{"id": "datasheet-vision"}]}),
        response(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "ping",
                                        "arguments": json.dumps(
                                            {"message": qualifier.PING_MESSAGE}
                                        ),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        response({"choices": [{"message": {"content": "red, green, blue, yellow"}}]}),
    ]


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    return json.loads((LANE_DIR / "contract.json").read_text())


def test_contract_and_plan_validate_against_strict_schemas(
    contract: dict[str, Any],
) -> None:
    contract_schema = json.loads((LANE_DIR / "contract.schema.json").read_text())
    evidence_schema = json.loads((LANE_DIR / "evidence.schema.json").read_text())
    jsonschema.Draft202012Validator(contract_schema).validate(contract)
    plan = qualifier.build_plan()
    jsonschema.Draft202012Validator(evidence_schema).validate(plan)
    assert plan["status"] == "planned"
    assert plan["requests_attempted"] == 0
    assert all(item["status"] == "planned" for item in plan["checks"])


def test_schema_rejects_unknown_contract_and_evidence_fields(
    contract: dict[str, Any],
) -> None:
    contract_schema = json.loads((LANE_DIR / "contract.schema.json").read_text())
    evidence_schema = json.loads((LANE_DIR / "evidence.schema.json").read_text())
    bad_contract = copy.deepcopy(contract)
    bad_contract["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(contract_schema).validate(bad_contract)
    bad_evidence = qualifier.build_plan()
    bad_evidence["secret"] = "must never be accepted"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(evidence_schema).validate(bad_evidence)


def test_evidence_schema_rejects_fabricated_or_rebound_pass() -> None:
    schema = json.loads((LANE_DIR / "evidence.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    evidence = qualifier._evidence(
        "passed",
        qualifier._file_sha256(qualifier.CONTRACT_PATH),
        4,
        [{"id": probe_id, "status": "passed"} for probe_id in qualifier.PROBE_IDS],
    )
    validator.validate(evidence)

    no_checks = copy.deepcopy(evidence)
    no_checks["checks"] = []
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(no_checks)

    wrong_lock = copy.deepcopy(evidence)
    wrong_lock["binding"]["artifact_lock_sha256"] = "0" * 64
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(wrong_lock)

    partial_pass = copy.deepcopy(evidence)
    partial_pass["requests_attempted"] = 3
    partial_pass["checks"][-1]["status"] = "not-run"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(partial_pass)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: value["runtime"]["endpoints"]["llm"].update(
                base_url="http://example.com"
            ),
            "contract_not_exact",
        ),
        (
            lambda value: value["runtime"]["endpoints"]["llm"].update(
                base_url="http://10.0.0.10:8000"
            ),
            "contract_not_exact",
        ),
        (
            lambda value: value["runtime"]["endpoints"]["vlm"].update(
                base_url="http://172.17.0.1:9003"
            ),
            "contract_not_exact",
        ),
        (
            lambda value: value["runtime"]["endpoints"]["vlm"].update(
                served_model_id="official-looking-model"
            ),
            "contract_not_exact",
        ),
        (
            lambda value: value["execution_policy"].update(maximum_http_requests=5),
            "contract_not_exact",
        ),
        (
            lambda value: value["artifact_lock"].update(sha256="0" * 64),
            "contract_not_exact",
        ),
        (
            lambda value: value["execution_policy"].update(proxies_allowed=True),
            "contract_not_exact",
        ),
        (
            lambda value: value["classification"].update(
                official_capability_promotion_allowed=True
            ),
            "contract_not_exact",
        ),
        (
            lambda value: value["artifact_lock"]["artifacts"]["qwen_vlm"].update(
                revision="0" * 40
            ),
            "contract_not_exact",
        ),
    ],
)
def test_security_or_identity_contract_tamper_fails_closed(
    contract: dict[str, Any], mutation: Any, code: str
) -> None:
    candidate = copy.deepcopy(contract)
    mutation(candidate)
    with pytest.raises(qualifier.QualificationError, match=code):
        qualifier.validate_contract(candidate)


def test_default_cli_is_inert_plan_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualifier.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "planned"
    assert output["requests_attempted"] == 0


def test_ack_without_execute_and_wrong_ack_fail_before_transport(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden_transport() -> None:
        raise AssertionError("transport must not be constructed")

    monkeypatch.setattr(qualifier, "DirectLocalTransport", forbidden_transport)
    assert qualifier.main(["--ack", qualifier.ACKNOWLEDGEMENT]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert qualifier.main(["--execute", "--ack", "yes"]) == 1
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["checks"][0]["diagnostic"] == "exact_acknowledgement_required"


def test_success_is_exactly_four_requests_and_redacted_evidence() -> None:
    transport = FakeTransport(successful_results())
    evidence = qualifier.execute(transport)
    assert evidence["status"] == "passed"
    assert evidence["requests_attempted"] == 4
    assert len(transport.requests) == 4
    assert [(item[0], item[1], item[2]) for item in transport.requests] == [
        ("llm", "GET", "/v1/models"),
        ("vlm", "GET", "/v1/models"),
        ("llm", "POST", "/v1/chat/completions"),
        ("vlm", "POST", "/v1/chat/completions"),
    ]
    rendered = json.dumps(evidence)
    assert "choices" not in rendered
    assert qualifier.PING_MESSAGE not in rendered
    assert evidence["classification"] == "non-official-local-alternate"
    assert not evidence["policy"]["official_capability_promotion_allowed"]


def test_llm_payload_disables_thinking_and_forces_exact_ping_tool() -> None:
    payload = qualifier._llm_payload()
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["model"] == "datasheet-chat"
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "ping"},
    }
    assert (
        payload["tools"][0]["function"]["parameters"]["additionalProperties"] is False
    )
    altered = copy.deepcopy(payload)
    del altered["chat_template_kwargs"]
    with pytest.raises(
        qualifier.QualificationError, match="llm_request_contract_not_exact"
    ):
        qualifier._validate_llm_payload(altered)


def test_vlm_payload_has_only_four_in_memory_locked_png_data_urls() -> None:
    payload = qualifier._vlm_payload()
    assert payload["model"] == "datasheet-vision"
    content = payload["messages"][0]["content"]
    images = content[1:]
    assert len(images) == 4
    assert all(
        item["image_url"]["url"].startswith("data:image/png;base64,") for item in images
    )
    assert "http://" not in json.dumps(images)
    assert "https://" not in json.dumps(images)
    for altered_images in (images[:-1], images + [images[0]], list(reversed(images))):
        altered = copy.deepcopy(payload)
        altered["messages"][0]["content"] = [content[0], *altered_images]
        with pytest.raises(
            qualifier.QualificationError, match="vlm_request_contract_not_exact"
        ):
            qualifier._validate_vlm_payload(altered)


def test_contract_rejects_wrong_image_count_and_order(contract: dict[str, Any]) -> None:
    for images in (
        contract["probes"][3]["images"][:-1],
        list(reversed(contract["probes"][3]["images"])),
    ):
        altered = copy.deepcopy(contract)
        altered["probes"][3]["images"] = images
        with pytest.raises(qualifier.QualificationError, match="contract_not_exact"):
            qualifier.validate_contract(altered)


@pytest.mark.parametrize(
    ("results", "diagnostic", "attempts"),
    [
        (
            [response({"data": [{"id": "datasheet-chat"}, {"id": "other"}]})],
            "model_identity_not_exact",
            1,
        ),
        ([response({}, status=302)], "unexpected_http_status", 1),
        (
            [qualifier.HttpResult(200, "text/html", b"not json")],
            "unexpected_content_type",
            1,
        ),
    ],
)
def test_identity_redirect_and_content_type_fail_closed_without_followup(
    results: list[Any], diagnostic: str, attempts: int
) -> None:
    transport = FakeTransport(results)
    evidence = qualifier.execute(transport)
    assert evidence["status"] == "failed"
    assert evidence["requests_attempted"] == attempts
    assert evidence["checks"][0]["diagnostic"] == diagnostic
    assert evidence["checks"][1]["status"] == "not-run"


def test_bad_tool_arguments_stop_before_vlm() -> None:
    results = successful_results()
    results[2] = response(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "ping",
                                    "arguments": '{"message":"wrong"}',
                                }
                            }
                        ]
                    }
                }
            ]
        }
    )
    transport = FakeTransport(results)
    evidence = qualifier.execute(transport)
    assert evidence["status"] == "failed"
    assert transport.requests_attempted == 3
    assert evidence["checks"][2]["diagnostic"] == "llm_tool_arguments_not_exact"
    assert evidence["checks"][3]["status"] == "not-run"


def test_wrong_visual_answer_is_not_accepted() -> None:
    results = successful_results()
    results[3] = response({"choices": [{"message": {"content": "blue, red"}}]})
    transport = FakeTransport(results)
    evidence = qualifier.execute(transport)
    assert evidence["status"] == "failed"
    assert transport.requests_attempted == 4
    assert evidence["checks"][3]["diagnostic"] == "vlm_color_order_not_exact"


def test_transport_has_closed_request_surface_and_limit() -> None:
    transport = qualifier.DirectLocalTransport()
    with pytest.raises(qualifier.QualificationError, match="request_not_allowlisted"):
        transport.request("llm", "GET", "http://example.com", b"")
    transport.requests_attempted = 4
    with pytest.raises(qualifier.QualificationError, match="request_limit_exceeded"):
        transport.request("llm", "GET", "/v1/models", b"")


def test_transport_uses_exact_direct_host_port_timeout_and_safe_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: dict[str, Any] = {}

    class FakeResponse:
        status = 200

        @staticmethod
        def getheader(name: str, default: str | None = None) -> str | None:
            return {"Content-Length": "11", "Content-Type": "application/json"}.get(
                name, default
            )

        @staticmethod
        def read(amount: int) -> bytes:
            observations["read_limit"] = amount
            return b'{"data":[]}'

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            observations["connection"] = (host, port, timeout)

        def request(
            self,
            method: str,
            path: str,
            body: bytes | None,
            headers: dict[str, str],
        ) -> None:
            observations["request"] = (method, path, body, headers)

        @staticmethod
        def getresponse() -> FakeResponse:
            return FakeResponse()

        @staticmethod
        def close() -> None:
            observations["closed"] = True

    monkeypatch.setattr(qualifier.http.client, "HTTPConnection", FakeConnection)
    result = qualifier.DirectLocalTransport().request("vlm", "GET", "/v1/models", b"")
    assert result.status == 200
    assert observations["connection"] == ("172.17.0.1", 8003, 10)
    method, path, body, headers = observations["request"]
    assert (method, path, body) == ("GET", "/v1/models", None)
    assert set(headers) == {"Accept", "Connection", "Content-Type"}
    assert observations["read_limit"] == qualifier.MAX_RESPONSE_BODY + 1
    assert observations["closed"] is True


def test_transport_enforces_request_and_declared_response_body_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = qualifier.DirectLocalTransport()
    with pytest.raises(qualifier.QualificationError, match="request_body_too_large"):
        transport.request(
            "llm",
            "POST",
            "/v1/chat/completions",
            b"x" * (qualifier.MAX_REQUEST_BODY + 1),
        )
    assert transport.requests_attempted == 0

    class OversizeResponse:
        status = 200

        @staticmethod
        def getheader(name: str, default: str | None = None) -> str | None:
            if name == "Content-Length":
                return str(qualifier.MAX_RESPONSE_BODY + 1)
            return default

    class OversizeConnection:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            pass

        @staticmethod
        def request(method: str, path: str, body: bytes | None, headers: Any) -> None:
            pass

        @staticmethod
        def getresponse() -> OversizeResponse:
            return OversizeResponse()

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr(qualifier.http.client, "HTTPConnection", OversizeConnection)
    with pytest.raises(qualifier.QualificationError, match="response_body_too_large"):
        qualifier.DirectLocalTransport().request("llm", "GET", "/v1/models", b"")


def test_source_has_no_mutation_subprocess_download_or_credential_path() -> None:
    source = QUALIFIER_PATH.read_text()
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported_roots & {"subprocess", "docker", "requests", "urllib", "os"}
    assert "Authorization" not in source
    assert "Proxy" not in source
    assert "write_text" not in source
    assert "write_bytes" not in source
    assert "open(" not in source
    assert "redirect" in source


def test_artifact_binding_is_exact_and_current(contract: dict[str, Any]) -> None:
    qualifier.validate_artifact_lock()
    assert (
        qualifier._file_sha256(qualifier.ARTIFACT_LOCK_PATH)
        == contract["artifact_lock"]["sha256"]
    )
    assert contract["runtime"]["vllm_image"] == qualifier.VLLM_IMAGE
    assert contract["source_binding"] == {
        "product_version": "3.2.1",
        "release_commit": qualifier.RELEASE_COMMIT,
        "reviewed_main_commit": qualifier.MAIN_COMMIT,
        "reviewed_local_base_commit": qualifier.LOCAL_BASE_COMMIT,
        "current_commit_source": ".git/HEAD (resolved read-only without subprocess)",
    }
    plan = qualifier.build_plan()
    assert plan["binding"]["current_commit"] == qualifier._read_current_commit()
    assert len(plan["binding"]["current_commit"]) == 40


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(classification="official-edge"),
        lambda value: value["policy"].update(
            official_capability_promotion_allowed=True
        ),
        lambda value: value.update(official_capabilities_advanced=["agent.chat"]),
        lambda value: value.update(official_edge_qualified=True),
    ],
)
def test_evidence_schema_rejects_any_official_or_capability_advancement_claim(
    mutation: Any,
) -> None:
    schema = json.loads((LANE_DIR / "evidence.schema.json").read_text())
    evidence = qualifier.build_plan()
    mutation(evidence)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(evidence)
