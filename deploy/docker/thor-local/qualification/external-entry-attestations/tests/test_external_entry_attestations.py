"""Isolated, collection-safe tests for the external-entry attestation lane."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("external_entry_plan", LANE / "plan.py")
assert SPEC and SPEC.loader
plan_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan_module)

H = "a" * 64


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _endpoint(host: str, provider_kind: str, index: int) -> dict:
    return {
        "scheme": "https",
        "hostname": host,
        "port": 443,
        "path_sha256": H,
        "tls_verified": True,
        "user_managed": True,
        "account_scope_sha256": H,
        "credential_material_included": False,
        "service_identity": {
            "provider_kind": provider_kind,
            "authority_hostname": host,
            "verification_method": "tls_certificate_and_authenticated_provider_probe",
            "tls_peer_certificate_sha256": _digest(f"certificate-{index}"),
            "provider_identity_receipt_sha256": _digest(f"identity-{index}"),
        },
    }


def _request(kind: str, operation: str, correlation: str, index: int) -> dict:
    return {
        "correlation_id": correlation,
        "timestamp": "2026-08-01T10:00:00Z",
        "operation": operation,
        "payload_sha256": _digest(f"payload-{index}"),
        "test_artifact": {
            "artifact_id": f"test-{kind}",
            "kind": kind,
            "sha256": _digest(f"artifact-{index}"),
            "size_bytes": 16,
        },
        "authentication_result": "authorized_without_recording_credential",
        "sanitized_headers_sha256": H,
    }


def _response(correlation: str, index: int) -> dict:
    return {
        "correlation_id": correlation,
        "timestamp": "2026-08-01T10:00:01Z",
        "http_status": 200,
        "body_sha256": _digest(f"response-{index}"),
        "provider_request_id_sha256": _digest(f"provider-request-{index}"),
        "success": True,
    }


def _cleanup(artifact: dict, receipt: str, policy: str = "delete") -> dict:
    return {
        "policy": policy,
        "completed_at": "2026-08-01T10:00:02Z",
        "owned_artifact_only": True,
        "artifact_id": artifact["artifact_id"],
        "artifact_sha256": artifact["sha256"],
        "provider_receipt_sha256": receipt,
        "deletion_confirmed": policy == "delete",
        "retention_expires_at": (
            "2026-08-02T10:00:02Z" if policy == "retain_with_expiry" else None
        ),
    }


def complete_evidence() -> dict:
    compiled = plan_module.compile_plan()
    attestations = []
    attestation_set_id = "operator-run-20260801"
    requests = [
        _request(kind, f"external.check-{index}", f"correlation-{index}", index)
        for index, kind in enumerate(["incident", "object", "document", "document"])
    ]
    responses = [_response(f"correlation-{index}", index) for index in range(4)]
    identities = [_digest(f"identity-{index}") for index in range(4)]
    cleanup_receipts = [_digest(f"cleanup-{index}") for index in range(4)]
    excerpts = [
        _digest("unused-0"),
        _digest("unused-1"),
        _digest("excerpt-2"),
        _digest("excerpt-3"),
    ]
    citations = [
        _digest("unused-citation-0"),
        _digest("unused-citation-1"),
        _digest("citation-2"),
        _digest("citation-3"),
    ]
    proofs = [
        {
            "proof_type": "slack_delivery",
            "provider_identity_receipt_sha256": identities[0],
            "incident_sha256": requests[0]["test_artifact"]["sha256"],
            "payload_incident_sha256": requests[0]["test_artifact"]["sha256"],
            "channel_identity_sha256": H,
            "message_timestamp_sha256": H,
            "delivery_response_sha256": responses[0]["body_sha256"],
            "delivery_provider_request_id_sha256": responses[0][
                "provider_request_id_sha256"
            ],
            "cleanup_receipt_sha256": cleanup_receipts[0],
            "delivery_receipt_correlated": True,
            "destination_observed_real": True,
        },
        {
            "proof_type": "aws_gcs_object_validation",
            "provider": "aws_s3",
            "actual_provider": "aws_s3",
            "provider_identity_receipt_sha256": identities[1],
            "provider_service_verified": True,
            "operator_endpoint_used": False,
            "local_emulator_used": False,
            "claimed_local_equivalence": False,
            "object_key_sha256": H,
            "uploaded_object_sha256": requests[1]["test_artifact"]["sha256"],
            "upload_confirmed": True,
            "readback_sha256": requests[1]["test_artifact"]["sha256"],
            "validation_response_sha256": responses[1]["body_sha256"],
            "validation_passed": True,
            "cleanup_receipt_sha256": cleanup_receipts[1],
            "delete_or_retention_receipt_sha256": cleanup_receipts[1],
        },
        {
            "proof_type": "enterprise_rag_report",
            "provider_identity_receipt_sha256": identities[2],
            "document_sha256": requests[2]["test_artifact"]["sha256"],
            "ingestion_document_sha256": requests[2]["test_artifact"]["sha256"],
            "ingestion_receipt_sha256": H,
            "query_sha256": requests[2]["payload_sha256"],
            "retrieval_response_sha256": responses[2]["body_sha256"],
            "retrieved_excerpt_sha256": excerpts[2],
            "citation_source_excerpt_sha256": excerpts[2],
            "citation_sha256": citations[2],
            "report_source_excerpt_sha256": excerpts[2],
            "report_citation_sha256": citations[2],
            "report_sha256": _digest("report-2"),
            "cleanup_receipt_sha256": cleanup_receipts[2],
            "report_contains_correlated_citation": True,
            "report_content_grounded_in_retrieved_excerpt": True,
        },
        {
            "proof_type": "frag_retrieval",
            "provider_identity_receipt_sha256": identities[3],
            "document_sha256": requests[3]["test_artifact"]["sha256"],
            "ingestion_document_sha256": requests[3]["test_artifact"]["sha256"],
            "ingestion_receipt_sha256": H,
            "collection_identity_sha256": H,
            "query_sha256": requests[3]["payload_sha256"],
            "retrieval_response_sha256": responses[3]["body_sha256"],
            "result_count": 1,
            "retrieved_excerpt_sha256": excerpts[3],
            "citation_source_excerpt_sha256": excerpts[3],
            "citation_sha256": citations[3],
            "cleanup_receipt_sha256": cleanup_receipts[3],
            "document_query_excerpt_citation_correlated": True,
        },
    ]
    hosts = ["slack.com", "s3.amazonaws.com", "rag.operator.net", "rag.operator.net"]
    provider_kinds = ["slack_api", "aws_s3", "enterprise_rag", "enterprise_rag"]
    for index, entry in enumerate(compiled["entries"]):
        attestations.append(
            {
                "entry_id": entry["entry_id"],
                "attestation_set_id": attestation_set_id,
                "acceptance_class": entry["acceptance_class"],
                "provider_scope": entry["provider_scope"],
                "endpoint": _endpoint(hosts[index], provider_kinds[index], index),
                "request": requests[index],
                "response": responses[index],
                "proof": proofs[index],
                "cleanup": _cleanup(
                    requests[index]["test_artifact"], cleanup_receipts[index]
                ),
            }
        )
    return {
        "schema_version": 1,
        "mode": "future_sanitized_operator_evidence",
        "package_id": "thor-external-entry-attestations-v1",
        "plan_sha256": plan_module._canonical_sha256(compiled),
        "attestation_set_id": attestation_set_id,
        "attestations": attestations,
        "boundary": {
            "credential_values_inspected": False,
            "credential_material_included": False,
            "source_or_mock_counted_as_delivery": False,
            "local_emulator_counted_as_aws_gcs": False,
            "generated_by_plan_package": False,
        },
    }


def rejects(value: dict, text: str) -> None:
    with pytest.raises(plan_module.AttestationError, match=text):
        plan_module.validate_evidence(value)


def test_plan_is_exact_inert_denominator() -> None:
    value = plan_module.compile_plan()
    assert [row["entry_id"] for row in value["entries"]] == plan_module.EXPECTED_IDS
    assert [row["acceptance_class"] for row in value["entries"]] == [
        "external_optional",
        "alternate_local_lane",
        "external_optional",
        "external_optional",
    ]
    assert value["summary"] == {
        "blocked_entries": 4,
        "external_optional": 3,
        "alternate_local_lane": 1,
        "accepted_attestations": 0,
        "runtime_evidence_added": False,
        "official_state_changed": False,
    }
    assert all(row["runtime_evidence"] == [] for row in value["entries"])
    assert all(row["source_or_mock_is_proof"] is False for row in value["entries"])


def test_pinned_contract_and_schemas_match_raw_bytes() -> None:
    for path, expected in [
        (plan_module.CONTRACT_PATH, plan_module.CONTRACT_SHA256),
        (plan_module.CONTRACT_SCHEMA_PATH, plan_module.CONTRACT_SCHEMA_SHA256),
        (plan_module.EVIDENCE_SCHEMA_PATH, plan_module.EVIDENCE_SCHEMA_SHA256),
    ]:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_source_locks_are_real_and_semantically_present() -> None:
    value = plan_module.compile_plan()
    assert len(value["source_checks"]) >= 10
    assert all(row["sha256_match"] for row in value["source_checks"])
    assert all(row["semantic_fragments_match"] for row in value["source_checks"])


def test_contract_and_source_raw_tamper_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = tmp_path / "contract.json"
    contract.write_bytes(plan_module.CONTRACT_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(plan_module, "CONTRACT_PATH", contract)
    with pytest.raises(plan_module.AttestationError, match="raw SHA-256 mismatch"):
        plan_module.compile_plan()

    source = tmp_path / "source.txt"
    source.write_text("altered")
    with pytest.raises(plan_module.AttestationError, match="raw SHA-256 mismatch"):
        plan_module._repo_source(tmp_path, "source.txt", H)


def test_script_has_no_active_external_or_write_capabilities() -> None:
    tree = ast.parse((LANE / "plan.py").read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported.isdisjoint(
        {"requests", "httpx", "urllib", "socket", "subprocess", "docker", "boto3"}
    )
    forbidden_calls = {
        "write",
        "write_text",
        "write_bytes",
        "unlink",
        "remove",
        "rename",
        "replace",
        "mkdir",
        "makedirs",
        "rmdir",
        "removedirs",
        "system",
        "popen",
    }
    forbidden_flags = {
        "O_WRONLY",
        "O_RDWR",
        "O_CREAT",
        "O_TRUNC",
        "O_APPEND",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert not (isinstance(node.func, ast.Name) and node.func.id == "open")
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "open":
                    assert isinstance(node.func.value, ast.Name)
                    assert node.func.value.id == "os"
                assert node.func.attr not in forbidden_calls
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            assert node.attr not in forbidden_flags


def test_complete_sanitized_attestation_validates_without_promotion() -> None:
    result = plan_module.validate_evidence(complete_evidence())
    assert result["validated_entries"] == 4
    assert result["qualified_entries"] == 0
    assert result["promotion_eligible"] is False
    assert result["credentials_inspected"] is False
    assert result["network_used"] is False
    assert result["official_state_changed"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["attestations"][0]["endpoint"].update({"scheme": "http"}),
        lambda value: value["attestations"][2]["endpoint"].update(
            {"tls_verified": False}
        ),
    ],
)
def test_https_and_verified_tls_are_mandatory(mutation) -> None:
    value = complete_evidence()
    mutation(value)
    rejects(value, "schema violation")


def test_slack_host_and_tls_authority_are_exact() -> None:
    value = complete_evidence()
    endpoint = value["attestations"][0]["endpoint"]
    endpoint["hostname"] = "hooks.slack.com"
    endpoint["service_identity"]["authority_hostname"] = "hooks.slack.com"
    rejects(value, "exact Slack API host")

    value = complete_evidence()
    value["attestations"][2]["endpoint"]["service_identity"][
        "authority_hostname"
    ] = "other.operator.net"
    rejects(value, "TLS authority and endpoint differ")


@pytest.mark.parametrize("hostname", ["127.0.0.1", "10.0.0.8", "rag.local"])
def test_loopback_private_and_local_operator_endpoints_are_rejected(
    hostname: str,
) -> None:
    value = complete_evidence()
    row = value["attestations"][1]
    row["proof"]["provider"] = "operator_supplied_actual_aws_or_gcs_endpoint"
    row["proof"]["operator_endpoint_used"] = True
    row["endpoint"]["hostname"] = hostname
    row["endpoint"]["service_identity"]["authority_hostname"] = hostname
    rejects(value, "endpoint (address is not globally routable|is local)")


def test_provider_service_identity_is_bound_to_proof() -> None:
    value = complete_evidence()
    value["attestations"][1]["proof"]["actual_provider"] = "gcs_hmac"
    rejects(value, "service identity is inconsistent")

    value = complete_evidence()
    value["attestations"][2]["endpoint"]["service_identity"]["provider_kind"] = "aws_s3"
    rejects(value, "Enterprise RAG identity is inconsistent")

    value = complete_evidence()
    value["attestations"][3]["proof"]["provider_identity_receipt_sha256"] = "b" * 64
    rejects(value, "provider identity receipt is uncorrelated")


@pytest.mark.parametrize(
    ("entry_index", "proof_field", "message"),
    [
        (0, "delivery_response_sha256", "Slack incident"),
        (1, "uploaded_object_sha256", "object readback"),
        (1, "validation_response_sha256", "object readback"),
        (1, "delete_or_retention_receipt_sha256", "object readback"),
        (2, "ingestion_document_sha256", "report/document"),
        (2, "query_sha256", "report/document"),
        (2, "retrieval_response_sha256", "report/document"),
        (2, "citation_source_excerpt_sha256", "report/document"),
        (2, "report_source_excerpt_sha256", "report/document"),
        (2, "report_citation_sha256", "report/document"),
        (3, "ingestion_document_sha256", "retrieval/document"),
        (3, "query_sha256", "retrieval/document"),
        (3, "retrieval_response_sha256", "retrieval/document"),
        (3, "citation_source_excerpt_sha256", "retrieval/document"),
    ],
)
def test_explicit_proof_digest_correlations_fail_closed(
    entry_index: int, proof_field: str, message: str
) -> None:
    value = complete_evidence()
    value["attestations"][entry_index]["proof"][proof_field] = "b" * 64
    rejects(value, message)


def test_cleanup_is_bound_to_exact_artifact_and_provider_receipt() -> None:
    value = complete_evidence()
    value["attestations"][2]["cleanup"]["artifact_sha256"] = "b" * 64
    rejects(value, "cleanup artifact correlation failed")

    value = complete_evidence()
    value["attestations"][3]["cleanup"]["provider_receipt_sha256"] = "b" * 64
    rejects(value, "cleanup provider receipt is uncorrelated")


def test_set_and_request_identifiers_cannot_be_replayed() -> None:
    value = complete_evidence()
    value["attestations"][0]["attestation_set_id"] = "different-set-id"
    rejects(value, "attestation set binding failed")

    value = complete_evidence()
    value["attestations"][1]["request"]["correlation_id"] = value["attestations"][0][
        "request"
    ]["correlation_id"]
    value["attestations"][1]["response"]["correlation_id"] = value["attestations"][0][
        "response"
    ]["correlation_id"]
    rejects(value, "correlation IDs must be unique")

    value = complete_evidence()
    value["attestations"][1]["response"]["provider_request_id_sha256"] = value[
        "attestations"
    ][0]["response"]["provider_request_id_sha256"]
    rejects(value, "provider request IDs must be unique")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "schema violation"),
        (lambda value: value.update({"plan_sha256": "b" * 64}), "exact plan"),
        (
            lambda value: value["attestations"][0]["response"].update(
                {"correlation_id": "different-correlation"}
            ),
            "correlation failed",
        ),
        (
            lambda value: value["attestations"][0]["response"].update(
                {"timestamp": "2026-08-01T09:59:59Z"}
            ),
            "predates request",
        ),
        (
            lambda value: value["attestations"][0]["proof"].update(
                {"incident_sha256": "b" * 64}
            ),
            "Slack incident",
        ),
        (
            lambda value: value["attestations"][1]["proof"].update(
                {"readback_sha256": "b" * 64}
            ),
            "object readback",
        ),
        (
            lambda value: value["attestations"][2]["proof"].update(
                {"document_sha256": "b" * 64}
            ),
            "report/document",
        ),
        (
            lambda value: value["attestations"][3]["proof"].update(
                {"document_sha256": "b" * 64}
            ),
            "retrieval/document",
        ),
    ],
)
def test_adversarial_semantic_evidence_is_rejected(mutation, message) -> None:
    value = complete_evidence()
    mutation(value)
    rejects(value, message)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["attestations"].reverse(),
            "denominator or order",
        ),
        (
            lambda value: value["attestations"][0].update(
                {"acceptance_class": "alternate_local_lane"}
            ),
            "acceptance class drifted",
        ),
        (
            lambda value: value["attestations"][0].update(
                {"provider_scope": "user_managed_enterprise_rag"}
            ),
            "provider scope drifted",
        ),
        (
            lambda value: value["attestations"][0].update(
                {"proof": value["attestations"][3]["proof"]}
            ),
            "proof type drifted",
        ),
    ],
)
def test_identity_and_proof_substitution_is_rejected(mutation, message) -> None:
    value = complete_evidence()
    mutation(value)
    rejects(value, message)


def test_secret_material_marker_is_rejected() -> None:
    value = complete_evidence()
    value["attestations"][0]["endpoint"]["hostname"] = "AKIA123456789012.example.com"
    rejects(value, "credential marker")


def test_local_emulator_and_mock_proof_are_rejected() -> None:
    value = complete_evidence()
    value["attestations"][1]["proof"]["local_emulator_used"] = True
    rejects(value, "schema violation")
    value = complete_evidence()
    value["boundary"]["source_or_mock_counted_as_delivery"] = True
    rejects(value, "schema violation")


def test_operator_endpoint_requires_actual_provider_identity() -> None:
    value = complete_evidence()
    proof = value["attestations"][1]["proof"]
    proof["provider"] = "operator_supplied_actual_aws_or_gcs_endpoint"
    proof["operator_endpoint_used"] = False
    rejects(value, "endpoint identity is inconsistent")


def test_direct_cloud_provider_cannot_claim_generic_endpoint() -> None:
    value = complete_evidence()
    value["attestations"][1]["endpoint"]["hostname"] = "minio.example.com"
    value["attestations"][1]["endpoint"]["service_identity"][
        "authority_hostname"
    ] = "minio.example.com"
    rejects(value, "does not identify an AWS endpoint")


def test_cleanup_and_retention_fail_closed() -> None:
    value = complete_evidence()
    row = value["attestations"][2]
    row["cleanup"] = _cleanup(
        row["request"]["test_artifact"],
        row["proof"]["cleanup_receipt_sha256"],
        "provider_message_retained",
    )
    rejects(value, "Slack-only")
    value = complete_evidence()
    row = value["attestations"][2]
    row["cleanup"] = _cleanup(
        row["request"]["test_artifact"],
        row["proof"]["cleanup_receipt_sha256"],
        "retain_with_expiry",
    )
    value["attestations"][2]["cleanup"]["retention_expires_at"] = "2026-08-01T10:00:01Z"
    rejects(value, "retention expiry")


def test_duplicate_json_and_symlink_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}')
    with pytest.raises(plan_module.AttestationError, match="duplicate JSON key"):
        plan_module._strict_json(duplicate.read_bytes(), "test")
    target = tmp_path / "target.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(plan_module.AttestationError, match="cannot read"):
        plan_module._read_regular(link, None, "test")


def test_descriptor_metadata_change_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "evidence.json"
    target.write_text("{}")
    real_fstat = plan_module.os.fstat
    calls = 0

    def unstable_fstat(descriptor: int):
        nonlocal calls
        calls += 1
        metadata = real_fstat(descriptor)
        if calls == 1:
            return metadata
        values = {
            field: getattr(metadata, field)
            for field in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        }
        values["st_mtime_ns"] += 1
        return SimpleNamespace(**values)

    monkeypatch.setattr(plan_module.os, "fstat", unstable_fstat)
    with pytest.raises(plan_module.AttestationError, match="changed while being read"):
        plan_module._read_regular(target, None, "test")


def test_cli_validation_requires_absolute_path(tmp_path: Path) -> None:
    assert plan_module.main(["validate", "--evidence", "relative.json"]) == 1
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(complete_evidence()))
    before = evidence.read_bytes()
    assert plan_module.main(["validate", "--evidence", str(evidence)]) == 0
    assert evidence.read_bytes() == before
