#!/usr/bin/env python3
"""Compile inert plans and validate sanitized future external attestations."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4].resolve(strict=True)
CONTRACT_PATH = LANE / "contract.json"
CONTRACT_SCHEMA_PATH = LANE / "contract.schema.json"
EVIDENCE_SCHEMA_PATH = LANE / "evidence.schema.json"
CONTRACT_SHA256 = "7d623638d48638279bc3342aa32d2c6bc44775871f85aeb6a320f8f3af0e429b"
CONTRACT_SCHEMA_SHA256 = (
    "082fc0841baa77e51bdcc530485e325315d64095ac491fbe2d923660452cdf35"
)
EVIDENCE_SCHEMA_SHA256 = (
    "27637afe3e1602a53997955f7e76c9c9cb3036d5609a03eb72ac81161296a41c"
)
MAX_BYTES = 4 * 1024 * 1024
EXPECTED_IDS = [
    "manifest-gap.alert-notifications-slack.00-slack-notification",
    "manifest-gap.spatial-ai-utils.07-aws-gcs-validation",
    "manifest-gap.enterprise-rag.00-rag-report-generation",
    "manifest-gap.enterprise-rag.01-frag-retrieval-integration",
]
SECRET_MARKERS = re.compile(
    r"(?i)(xox[a-z]-|AKIA[0-9A-Z]{12,}|bearer\s+|authorization\s*[:=]|"
    r"api[_-]?key\s*[:=]|secret[_-]?(?:access[_-]?)?key\s*[:=]|token\s*[:=])"
)


class AttestationError(RuntimeError):
    """A source lock, plan boundary, or future attestation failed closed."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _strict_json(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise AttestationError(f"duplicate JSON key in {label}: {key}")
            value[key] = item
        return value

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttestationError(f"invalid JSON in {label}") from exc


def _read_regular(path: Path, expected: str | None, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AttestationError(f"cannot read {label}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AttestationError(f"{label} must be a regular non-symlink file")
        if metadata.st_size <= 0 or metadata.st_size > MAX_BYTES:
            raise AttestationError(f"{label} exceeds the bounded size contract")
        chunks = []
        remaining = MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 128 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if not raw or len(raw) > MAX_BYTES:
            raise AttestationError(f"{label} exceeds the bounded size contract")
        final_metadata = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != metadata.st_size or any(
            getattr(metadata, field) != getattr(final_metadata, field)
            for field in stable_fields
        ):
            raise AttestationError(f"{label} changed while being read")
    finally:
        os.close(descriptor)
    if expected is not None and _sha256(raw) != expected:
        raise AttestationError(f"{label} raw SHA-256 mismatch")
    return raw


def _repo_source(root: Path, relative: str, expected: str) -> bytes:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise AttestationError("unsafe locked source path")
    root = root.resolve(strict=True)
    current = root
    for part in path.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise AttestationError(f"cannot read locked source: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise AttestationError(f"locked source contains a symlink: {relative}")
    return _read_regular(current, expected, f"locked source {relative}")


def _load_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = _strict_json(
        _read_regular(CONTRACT_PATH, CONTRACT_SHA256, "contract"), "contract"
    )
    contract_schema = _strict_json(
        _read_regular(CONTRACT_SCHEMA_PATH, CONTRACT_SCHEMA_SHA256, "contract schema"),
        "contract schema",
    )
    evidence_schema = _strict_json(
        _read_regular(EVIDENCE_SCHEMA_PATH, EVIDENCE_SCHEMA_SHA256, "evidence schema"),
        "evidence schema",
    )
    Draft202012Validator.check_schema(contract_schema)
    Draft202012Validator.check_schema(evidence_schema)
    contract_errors = list(Draft202012Validator(contract_schema).iter_errors(contract))
    if contract_errors:
        raise AttestationError(
            f"contract schema violation: {contract_errors[0].message}"
        )
    return contract, evidence_schema


def _source_checks(contract: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    locks = [contract["blocked_entries_source"], contract["gap_plan_source"]]
    locks.extend(
        lock for entry in contract["entries"] for lock in entry["source_locks"]
    )
    checks = []
    seen = set()
    for lock in locks:
        key = (lock["path"], lock["raw_sha256"])
        if key in seen:
            continue
        seen.add(key)
        raw = _repo_source(root, lock["path"], lock["raw_sha256"])
        text = raw.decode("utf-8")
        missing = [value for value in lock.get("fragments", []) if value not in text]
        if missing:
            raise AttestationError(
                f"locked semantic fragment missing in {lock['path']}: {missing[0]}"
            )
        checks.append(
            {
                "path": lock["path"],
                "raw_sha256": lock["raw_sha256"],
                "sha256_match": True,
                "semantic_fragments_match": True,
            }
        )
    return checks


def compile_plan(root: Path = REPO_ROOT) -> dict[str, Any]:
    contract, _schema = _load_contract()
    if [row["entry_id"] for row in contract["entries"]] != EXPECTED_IDS:
        raise AttestationError("four-entry denominator or order drifted")
    policy = contract["policy"]
    if policy["default_inert"] is not True or policy["read_only"] is not True:
        raise AttestationError("inert read-only policy drifted")
    forbidden = (
        "credential_inspection_allowed",
        "credential_material_allowed_in_evidence",
        "network_allowed",
        "subprocess_allowed",
        "docker_allowed",
        "file_writes_allowed",
        "lifecycle_allowed",
        "source_or_mock_is_delivery_proof",
        "can_mark_passed_current",
    )
    if any(policy[key] is not False for key in forbidden):
        raise AttestationError("inert secret-free policy drifted")
    if policy["runtime_evidence"] != []:
        raise AttestationError("plan contract contains runtime evidence")

    checks = _source_checks(contract, root)
    inventory = _strict_json(
        _repo_source(
            root,
            contract["blocked_entries_source"]["path"],
            contract["blocked_entries_source"]["raw_sha256"],
        ),
        "blocked inventory",
    )
    gap_plan = _strict_json(
        _repo_source(
            root,
            contract["gap_plan_source"]["path"],
            contract["gap_plan_source"]["raw_sha256"],
        ),
        "gap plan",
    )
    blocked = {row["entry_id"]: row for row in inventory["blocked_entries"]}
    gaps = {row["entry_id"]: row for row in gap_plan["entries"]}
    if set(blocked) != set(EXPECTED_IDS):
        raise AttestationError("Wave 7 blocker set is no longer the exact four entries")

    entries = []
    for row in contract["entries"]:
        entry_id = row["entry_id"]
        source_block = blocked[entry_id]
        source_gap = gaps[entry_id]
        if source_block["manifest_pointer"] != row["manifest_pointer"]:
            raise AttestationError("blocked manifest pointer drifted")
        if source_block["advertised"] != row["advertised"]:
            raise AttestationError("blocked advertised identity drifted")
        if source_block["blocker_type"] != "external_optional_boundary":
            raise AttestationError("external blocker type drifted")
        if source_gap["family_acceptance_class"] != row["acceptance_class"]:
            raise AttestationError("entry acceptance class drifted")
        if source_gap["required_oracle"]["status"] != "open_unexecuted":
            raise AttestationError("external entry oracle is no longer open")
        if source_gap["runtime_evidence"] != []:
            raise AttestationError("external entry unexpectedly has runtime evidence")
        entries.append(
            {
                "entry_id": entry_id,
                "manifest_pointer": row["manifest_pointer"],
                "advertised": row["advertised"],
                "acceptance_class": row["acceptance_class"],
                "provider_scope": row["provider_scope"],
                "evidence_type": row["evidence_type"],
                "blocker_type": source_block["blocker_type"],
                "required_future_evidence": [
                    "verified_https_and_sanitized_service_identity",
                    "authorized_request_and_success_response_timestamps",
                    "unique_request_response_and_provider_id_correlation",
                    "test_object_or_document_sha256",
                    "explicit_payload_query_response_retrieval_digest_correlation",
                    "real_delivery_or_excerpt_citation_report_correlation",
                    "artifact_and_provider_receipt_bound_cleanup_or_retention",
                ],
                "credential_values": "forbidden",
                "source_or_mock_is_proof": False,
                "acceptance_boundary": row["acceptance_boundary"],
                "state": "blocked_pending_external_attestation",
                "runtime_evidence": [],
            }
        )
    return {
        "schema_version": 1,
        "mode": "inert_read_only_plan",
        "package_id": contract["package_id"],
        "contract_sha256": CONTRACT_SHA256,
        "contract_schema_sha256": CONTRACT_SCHEMA_SHA256,
        "evidence_schema_sha256": EVIDENCE_SCHEMA_SHA256,
        "source_checks": checks,
        "entries": entries,
        "summary": {
            "blocked_entries": 4,
            "external_optional": 3,
            "alternate_local_lane": 1,
            "accepted_attestations": 0,
            "runtime_evidence_added": False,
            "official_state_changed": False,
        },
        "policy": policy,
        "boundary": (
            "Plan and validator only: no credentials are inspected, no network or "
            "service operation occurs, and shipped source or mocks never count as "
            "external delivery, storage, retrieval, citation, or report proof."
        ),
    }


def _timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _assert_public_endpoint(hostname: str, entry_id: str) -> None:
    hostname = hostname.lower().rstrip(".")
    if (
        "." not in hostname
        or hostname == "localhost"
        or hostname.endswith((".local", ".localhost", ".internal", ".lan", ".home"))
    ):
        raise AttestationError(f"{entry_id}: endpoint is local or not fully qualified")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise AttestationError(f"{entry_id}: endpoint address is not globally routable")


def _assert_service_identity(row: dict[str, Any]) -> None:
    entry_id = row["entry_id"]
    endpoint = row["endpoint"]
    identity = endpoint["service_identity"]
    hostname = endpoint["hostname"].lower().rstrip(".")
    authority = identity["authority_hostname"].lower().rstrip(".")
    if hostname != authority:
        raise AttestationError(f"{entry_id}: TLS authority and endpoint differ")
    _assert_public_endpoint(hostname, entry_id)
    if endpoint["scheme"] != "https" or endpoint["tls_verified"] is not True:
        raise AttestationError(f"{entry_id}: HTTPS with verified TLS is required")

    proof = row["proof"]
    if entry_id == EXPECTED_IDS[0]:
        if hostname not in {"slack.com", "api.slack.com"}:
            raise AttestationError("Slack evidence must use an exact Slack API host")
        if identity["provider_kind"] != "slack_api":
            raise AttestationError("Slack service identity is inconsistent")
    elif entry_id == EXPECTED_IDS[1]:
        actual_provider = proof["actual_provider"]
        expected_kind = "aws_s3" if actual_provider == "aws_s3" else "gcs_hmac"
        if identity["provider_kind"] != expected_kind:
            raise AttestationError("AWS/GCS service identity is inconsistent")
        if proof["provider"] != "operator_supplied_actual_aws_or_gcs_endpoint":
            if proof["provider"] != actual_provider:
                raise AttestationError("direct cloud provider identity is inconsistent")
        elif not proof["operator_endpoint_used"]:
            raise AttestationError("operator cloud endpoint identity is inconsistent")
    elif identity["provider_kind"] != "enterprise_rag":
        raise AttestationError(f"{entry_id}: Enterprise RAG identity is inconsistent")
    if (
        proof["provider_identity_receipt_sha256"]
        != identity["provider_identity_receipt_sha256"]
    ):
        raise AttestationError(f"{entry_id}: provider identity receipt is uncorrelated")


def _assert_cleanup(
    value: dict[str, Any],
    entry_id: str,
    artifact: dict[str, Any],
    proof: dict[str, Any],
) -> None:
    if (
        value["artifact_id"] != artifact["artifact_id"]
        or value["artifact_sha256"] != artifact["sha256"]
    ):
        raise AttestationError(f"{entry_id}: cleanup artifact correlation failed")
    if value["provider_receipt_sha256"] != proof["cleanup_receipt_sha256"]:
        raise AttestationError(f"{entry_id}: cleanup provider receipt is uncorrelated")
    policy = value["policy"]
    if policy == "delete":
        if not value["deletion_confirmed"] or value["retention_expires_at"] is not None:
            raise AttestationError(f"{entry_id}: delete cleanup proof is incomplete")
    elif policy == "retain_with_expiry":
        if value["deletion_confirmed"] or value["retention_expires_at"] is None:
            raise AttestationError(f"{entry_id}: retention expiry is incomplete")
    elif entry_id != EXPECTED_IDS[0] or value["deletion_confirmed"]:
        raise AttestationError("provider-message retention is Slack-only")


def validate_evidence(value: dict[str, Any]) -> dict[str, Any]:
    _contract, schema = _load_contract()
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors:
        raise AttestationError(f"evidence schema violation: {errors[0].message}")
    serialized = json.dumps(value, sort_keys=True)
    if SECRET_MARKERS.search(serialized):
        raise AttestationError("evidence contains a forbidden credential marker")
    plan = compile_plan()
    if value["plan_sha256"] != _canonical_sha256(plan):
        raise AttestationError("evidence is not bound to this exact plan")
    if [row["entry_id"] for row in value["attestations"]] != EXPECTED_IDS:
        raise AttestationError("attestation denominator or order differs from plan")

    plan_entries = {row["entry_id"]: row for row in plan["entries"]}
    correlation_ids: set[str] = set()
    provider_request_ids: set[str] = set()
    for row in value["attestations"]:
        entry_id = row["entry_id"]
        expected = plan_entries[entry_id]
        if row["acceptance_class"] != expected["acceptance_class"]:
            raise AttestationError(f"{entry_id}: acceptance class drifted")
        if row["provider_scope"] != expected["provider_scope"]:
            raise AttestationError(f"{entry_id}: provider scope drifted")
        if row["proof"]["proof_type"] != expected["evidence_type"]:
            raise AttestationError(f"{entry_id}: proof type drifted")
        if row["attestation_set_id"] != value["attestation_set_id"]:
            raise AttestationError(f"{entry_id}: attestation set binding failed")
        _assert_service_identity(row)
        request = row["request"]
        response = row["response"]
        if request["correlation_id"] != response["correlation_id"]:
            raise AttestationError(f"{entry_id}: request/response correlation failed")
        if _timestamp(response["timestamp"]) < _timestamp(request["timestamp"]):
            raise AttestationError(f"{entry_id}: response predates request")
        if _timestamp(row["cleanup"]["completed_at"]) < _timestamp(
            response["timestamp"]
        ):
            raise AttestationError(f"{entry_id}: cleanup predates response")
        retention = row["cleanup"]["retention_expires_at"]
        if retention is not None and _timestamp(retention) <= _timestamp(
            row["cleanup"]["completed_at"]
        ):
            raise AttestationError(f"{entry_id}: retention expiry is not future")
        proof = row["proof"]
        artifact_sha = request["test_artifact"]["sha256"]
        if request["correlation_id"] in correlation_ids:
            raise AttestationError("correlation IDs must be unique across attestations")
        correlation_ids.add(request["correlation_id"])
        if response["provider_request_id_sha256"] in provider_request_ids:
            raise AttestationError(
                "provider request IDs must be unique across attestations"
            )
        provider_request_ids.add(response["provider_request_id_sha256"])
        if entry_id == EXPECTED_IDS[0]:
            if (
                request["test_artifact"]["kind"] != "incident"
                or proof["incident_sha256"] != artifact_sha
                or proof["payload_incident_sha256"] != artifact_sha
                or proof["delivery_response_sha256"] != response["body_sha256"]
                or proof["delivery_provider_request_id_sha256"]
                != response["provider_request_id_sha256"]
            ):
                raise AttestationError("Slack incident/delivery correlation failed")
        elif entry_id == EXPECTED_IDS[1]:
            if (
                request["test_artifact"]["kind"] != "object"
                or proof["uploaded_object_sha256"] != artifact_sha
                or proof["readback_sha256"] != artifact_sha
                or proof["validation_response_sha256"] != response["body_sha256"]
                or proof["delete_or_retention_receipt_sha256"]
                != proof["cleanup_receipt_sha256"]
            ):
                raise AttestationError("AWS/GCS object readback correlation failed")
            operator_provider = (
                proof["provider"] == "operator_supplied_actual_aws_or_gcs_endpoint"
            )
            if proof["operator_endpoint_used"] is not operator_provider:
                raise AttestationError(
                    "operator AWS/GCS endpoint identity is inconsistent"
                )
            hostname = row["endpoint"]["hostname"].lower().rstrip(".")
            if proof["provider"] == "aws_s3" and not (
                hostname == "amazonaws.com" or hostname.endswith(".amazonaws.com")
            ):
                raise AttestationError("AWS S3 proof does not identify an AWS endpoint")
            if proof["provider"] == "gcs_hmac" and not (
                hostname == "storage.googleapis.com"
                or hostname.endswith(".storage.googleapis.com")
            ):
                raise AttestationError("GCS proof does not identify a GCS endpoint")
            if operator_provider and (
                hostname in {"localhost", "127.0.0.1", "::1"}
                or hostname.endswith((".local", ".localhost"))
            ):
                raise AttestationError("operator AWS/GCS endpoint is local or emulated")
        elif entry_id == EXPECTED_IDS[2]:
            if (
                request["test_artifact"]["kind"] != "document"
                or proof["document_sha256"] != artifact_sha
                or proof["ingestion_document_sha256"] != artifact_sha
                or proof["query_sha256"] != request["payload_sha256"]
                or proof["retrieval_response_sha256"] != response["body_sha256"]
                or proof["citation_source_excerpt_sha256"]
                != proof["retrieved_excerpt_sha256"]
                or proof["report_source_excerpt_sha256"]
                != proof["retrieved_excerpt_sha256"]
                or proof["report_citation_sha256"] != proof["citation_sha256"]
            ):
                raise AttestationError(
                    "Enterprise RAG report/document correlation failed"
                )
        else:
            if (
                request["test_artifact"]["kind"] != "document"
                or proof["document_sha256"] != artifact_sha
                or proof["ingestion_document_sha256"] != artifact_sha
                or proof["query_sha256"] != request["payload_sha256"]
                or proof["retrieval_response_sha256"] != response["body_sha256"]
                or proof["citation_source_excerpt_sha256"]
                != proof["retrieved_excerpt_sha256"]
            ):
                raise AttestationError("FRAG retrieval/document correlation failed")
        _assert_cleanup(row["cleanup"], entry_id, request["test_artifact"], proof)
    return {
        "schema_version": 1,
        "mode": "sanitized_read_only_validation",
        "validated_entries": 4,
        "qualified_entries": 0,
        "promotion_eligible": False,
        "credentials_inspected": False,
        "network_used": False,
        "official_state_changed": False,
        "boundary": "validation only; promotion requires a separate reviewed integration step",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("plan", help="print inert plan (default)")
    check = sub.add_parser(
        "validate", help="read-only validation of sanitized future evidence"
    )
    check.add_argument("--evidence", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in {None, "plan"}:
            result = compile_plan()
        else:
            path = Path(args.evidence)
            if not path.is_absolute():
                raise AttestationError("--evidence must be an absolute path")
            value = _strict_json(_read_regular(path, None, "evidence"), "evidence")
            result = validate_evidence(value)
    except (OSError, AttestationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
