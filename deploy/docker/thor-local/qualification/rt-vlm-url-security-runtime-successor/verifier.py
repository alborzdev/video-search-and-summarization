#!/usr/bin/env python3
"""Verify retained RT-VLM URL-ingestion security evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


class EvidenceError(RuntimeError):
    pass


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                EvidenceError(f"non-finite JSON: {token}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    receipt = _load(RECEIPT_PATH)
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt),
        key=lambda error: list(error.path),
    )
    if errors:
        raise EvidenceError(f"receipt schema violation: {errors[0].message}")
    if receipt["contract_sha256"] != _sha(CONTRACT_PATH):
        raise EvidenceError("receipt contract binding drifted")
    for key in ("capability_ids", "official_indices", "policy"):
        if receipt[key] != contract[key]:
            raise EvidenceError(f"{key} drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path) != lock["sha256"]:
            raise EvidenceError(f"source lock drifted: {lock['path']}")
    if UUID_PATTERN.search(RECEIPT_PATH.read_text(encoding="utf-8")):
        raise EvidenceError("receipt retained a raw request UUID")

    api = receipt["live_api"]
    if not api["ready"] or not api["url_present"] or not api["url_headers_present"]:
        raise EvidenceError("live RT-VLM URL API contract drifted")
    if api["loopback_ssrf_status_code"] != 422 or not api["loopback_rejected_before_download"]:
        raise EvidenceError("live API SSRF boundary drifted")

    auth = receipt["authentication"]
    if not all(auth["request_headers"].values()):
        raise EvidenceError("request-level URL header allowlist drifted")
    if not auth["environment_auth"]["authorization_delivered"]:
        raise EvidenceError("environment URL auth was not delivered")
    if not auth["environment_auth"]["unmatched_domain_authorization_stripped"]:
        raise EvidenceError("environment URL auth leaked cross-domain")
    for key in (
        "plain_http_authorization_stripped",
        "same_host_redirect_authorization_retained",
        "cross_host_redirect_authorization_stripped",
    ):
        if not auth[key]:
            raise EvidenceError(f"URL auth boundary drifted: {key}")

    redirects = receipt["redirects"]
    if redirects["zero"] != {"status_code": 422, "code": "RedirectNotAllowed", "requests": 1}:
        raise EvidenceError("zero-hop redirect boundary drifted")
    if redirects["one"] != {"status_code": 422, "code": "RedirectNotAllowed", "requests": 2}:
        raise EvidenceError("one-hop redirect boundary drifted")
    if redirects["two"] != {"downloaded": True, "requests": 3, "ssrf_validation_calls": 3}:
        raise EvidenceError("two-hop redirect success/validation drifted")
    if redirects["negative"]["effective_limit"] != 0:
        raise EvidenceError("negative redirect clamp drifted")
    if redirects["above_max"]["effective_limit"] != 10 or redirects["above_max"]["requests"] != 11:
        raise EvidenceError("maximum redirect clamp drifted")

    size = receipt["download_size"]
    if size["default_limit_bytes"] != 8 * 1024**3:
        raise EvidenceError("default URL download size drifted")
    if not (size["below_limit_bytes"] <= size["configured_limit_bytes"] < size["over_limit_response_bytes"]):
        raise EvidenceError("download-size boundary arithmetic drifted")
    if size["over_limit_status_code"] != 413 or not size["over_limit_not_saved"]:
        raise EvidenceError("over-limit rejection/atomicity drifted")

    tls = receipt["tls"]
    if not tls["default_verification"]["verified"] or not tls["default_verification"]["self_signed_rejected"]:
        raise EvidenceError("default TLS verification drifted")
    if not tls["listed_domain"]["verification_skipped"] or not tls["listed_domain"]["downloaded"]:
        raise EvidenceError("listed-domain TLS exception drifted")
    if not tls["unlisted_domain"]["verification_retained"] or not tls["unlisted_domain"]["self_signed_rejected"]:
        raise EvidenceError("unlisted-domain TLS verification drifted")

    if receipt["fixture_boundary"]["ssrf_guard_bypass"] != "bounded_fixture_hosts_only":
        raise EvidenceError("fixture-only SSRF boundary drifted")
    if receipt["fixture_boundary"]["raw_credentials_retained"]:
        raise EvidenceError("receipt retained raw credentials")
    if not all(value for key, value in receipt["cleanup"].items() if key != "failures"):
        raise EvidenceError("cleanup was not exact")
    if receipt["cleanup"]["failures"]:
        raise EvidenceError("cleanup recorded failures")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "show"), nargs="?", default="check")
    args = parser.parse_args(argv)
    try:
        receipt = verify()
        if args.mode == "show":
            print(json.dumps(receipt, indent=2, sort_keys=True))
        else:
            print(json.dumps({
                "status": "passed",
                "official_indices": receipt["official_indices"],
                "receipt_sha256": _sha(RECEIPT_PATH),
                "writes_or_lifecycle_actions": False,
            }, sort_keys=True))
        return 0
    except (EvidenceError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
