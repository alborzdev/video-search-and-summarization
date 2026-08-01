#!/usr/bin/env python3
"""Authorization-gated candidate-alert admission and cleanup collector.

The default command compiles an inert plan. Runtime HTTP is reachable only by
the explicit ``execute`` command, an exact acknowledgement, an exact run ID,
numeric-loopback targets, and an injected no-proxy/no-redirect opener.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Sequence
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
PLAN_SCHEMA_PATH = HERE / "plan.schema.json"
EVIDENCE_SCHEMA_PATH = HERE / "evidence.schema.json"
COMMON_PATH = HERE.parent / "runtime-evidence-common" / "common.py"
CAPABILITY_ORACLES_PATH = (
    REPO_ROOT / "deploy/docker/thor-local/parity/capability-oracles.json"
)
VERIFIED_INTEGRATIONS_PATH = (
    REPO_ROOT
    / "deploy/docker/thor-local/qualification/runtime-execution-bounds-audit/verified-integrations.json"
)
MAX_SOURCE_BYTES = 32 * 1024 * 1024
PLAIN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _load_common() -> Any:
    spec = importlib.util.spec_from_file_location(
        "candidate_alerts_runtime_evidence_common", COMMON_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


common = _load_common()


class CollectorError(RuntimeError):
    """Fail-closed collector error carrying one stable public code."""

    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "fixture_error",
        "invalid_response",
        "oracle_failed",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _bounded_read(path: Path, maximum: int = MAX_SOURCE_BYTES) -> bytes:
    if type(maximum) is not int or not 1 <= maximum <= MAX_SOURCE_BYTES:
        raise CollectorError("configuration_error")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CollectorError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise CollectorError("configuration_error")
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(131072, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, field) != getattr(after, field) for field in stable
        ):
            raise CollectorError("configuration_error")
        return raw
    finally:
        os.close(descriptor)


def _json(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    raw = _bounded_read(path)
    if (
        expected_sha256 is not None
        and hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise CollectorError("configuration_error")
    return _strict_json_raw(raw)


def _strict_json_raw(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CollectorError("configuration_error")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _token: (_ for _ in ()).throw(
                CollectorError("configuration_error")
            ),
        )
    except CollectorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectorError("configuration_error") from exc
    if not isinstance(value, dict):
        raise CollectorError("configuration_error")
    return value


def _validate(instance: Any, schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(instance))
    except Exception as exc:
        if isinstance(exc, CollectorError):
            raise
        raise CollectorError("configuration_error") from exc
    if errors:
        raise CollectorError("configuration_error")


def _contract() -> dict[str, Any]:
    contract = _json(CONTRACT_PATH)
    _validate(contract, _json(CONTRACT_SCHEMA_PATH))
    return contract


def _source_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise CollectorError("configuration_error")
    path = REPO_ROOT.joinpath(*candidate.parts)
    current = REPO_ROOT
    for part in candidate.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise CollectorError("configuration_error")
        except OSError as exc:
            raise CollectorError("configuration_error") from exc
    return path


def _unique(items: Sequence[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    matches = [
        item for item in items if isinstance(item, dict) and item.get(key) == value
    ]
    if len(matches) != 1:
        raise CollectorError("configuration_error")
    return matches[0]


def _validate_fixture(
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    locks = {item["path"]: item["sha256"] for item in contract["source_locks"]}
    manifest_path = (
        "deploy/docker/thor-local/qualification/local20-fixture-pack/manifest.json"
    )
    fixture_path = "deploy/docker/thor-local/qualification/local20-fixture-pack/fixtures/alerts-incidents-tracks.json"
    manifest = _json(_source_path(manifest_path), expected_sha256=locks[manifest_path])
    fixture = _json(_source_path(fixture_path), expected_sha256=locks[fixture_path])
    fixture_entry = _unique(
        manifest.get("json_fixtures", []),
        "fixture_id",
        "local20-alerts-incidents-tracks-v1",
    )
    if (
        fixture_entry.get("path") != "fixtures/alerts-incidents-tracks.json"
        or fixture_entry.get("raw_sha256") != locks[fixture_path]
        or "candidate-alerts" not in fixture_entry.get("covers", [])
        or fixture.get("fixture_id") != "local20-alerts-incidents-tracks-v1"
    ):
        raise CollectorError("fixture_error")
    alerts = fixture.get("alerts")
    if not isinstance(alerts, list):
        raise CollectorError("fixture_error")
    accepted = [
        item
        for item in alerts
        if isinstance(item, dict)
        and item.get("candidate") is True
        and item.get("vlm_verdict") == "verified"
        and item.get("expected_publish") is True
    ]
    rejected = [
        item
        for item in alerts
        if isinstance(item, dict)
        and item.get("candidate") is True
        and item.get("vlm_verdict") == "rejected"
        and item.get("expected_publish") is False
    ]
    if len(accepted) != 1 or len(rejected) != 1:
        raise CollectorError("fixture_error")
    required = {
        "alert_id",
        "sensor_id",
        "rule",
        "candidate",
        "vlm_verdict",
        "expected_publish",
    }
    if set(accepted[0]) != required or set(rejected[0]) != required:
        raise CollectorError("fixture_error")
    return accepted[0], rejected[0], locks[fixture_path]


def compile_plan() -> dict[str, Any]:
    contract = _contract()
    locks = {item["path"]: item["sha256"] for item in contract["source_locks"]}
    for relative, expected in locks.items():
        raw = _bounded_read(_source_path(relative))
        if hashlib.sha256(raw).hexdigest() != expected:
            raise CollectorError("configuration_error")
    _, _, fixture_sha = _validate_fixture(contract)

    expected_alerts_path = "deploy/docker/thor-local/qualification/expected/alerts.json"
    expected_alerts = _json(
        _source_path(expected_alerts_path), expected_sha256=locks[expected_alerts_path]
    )
    operations = {
        (item.get("method"), item.get("path"))
        for item in expected_alerts.get("operations", [])
        if isinstance(item, dict)
    }
    required_operations = {
        ("GET", "/health"),
        ("GET", "/api/v1/verification/config"),
        ("POST", "/api/v1/verification/config"),
        ("GET", "/api/v1/verification/config/{alert_type}"),
        ("DELETE", "/api/v1/verification/config/{alert_type}"),
        ("POST", "/api/v1/verification/ondemand"),
    }
    if not required_operations.issubset(operations):
        raise CollectorError("configuration_error")

    oracle_raw = _bounded_read(CAPABILITY_ORACLES_PATH)
    oracle_doc = _strict_json_raw(oracle_raw)
    oracle = _unique(
        oracle_doc.get("oracles", []),
        "oracle_id",
        contract["oracle_id"],
    )
    bounds = oracle.get("execution_bounds")
    if (
        oracle.get("capability_id") != contract["capability_id"]
        or not isinstance(bounds, dict)
        or bounds.get("max_requests") != 8
        or bounds.get("max_actions") != 8
        or bounds.get("warehouse_sample_bundle") != "excluded"
    ):
        raise CollectorError("configuration_error")

    integrations_raw = _bounded_read(VERIFIED_INTEGRATIONS_PATH)
    integrations = _strict_json_raw(integrations_raw)
    integration = _unique(
        integrations.get("cases", []),
        "planning_requirement_id",
        contract["planning_requirement_id"],
    )
    if (
        integration.get("capability_id") != contract["capability_id"]
        or integration.get("oracle_id") != contract["oracle_id"]
        or integration.get("integrated_max_requests") != 8
        or integration.get("integrated_max_actions") != 8
        or integration.get("integration_verified") is not True
    ):
        raise CollectorError("configuration_error")

    plan = {
        "schema_version": 1,
        "collector_id": contract["collector_id"],
        "mode": "inert-plan",
        "status": "pass",
        "runtime_actions": 0,
        "default_execution_enabled": False,
        "planning_requirement_id": contract["planning_requirement_id"],
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "contract_sha256": hashlib.sha256(_bounded_read(CONTRACT_PATH)).hexdigest(),
        "fixture_sha256": fixture_sha,
        "canonical_sources": {
            "capability_oracles_sha256": hashlib.sha256(oracle_raw).hexdigest(),
            "verified_integrations_sha256": hashlib.sha256(
                integrations_raw
            ).hexdigest(),
            "expected_alerts_sha256": locks[expected_alerts_path],
        },
        "execution_bounds": {
            key: contract["execution_bounds"][key]
            for key in (
                "max_requests",
                "max_actions",
                "max_request_bytes",
                "max_response_bytes",
                "timeout_seconds",
            )
        },
        "authorization": {
            "authorization_id": contract["authorization"]["authorization_id"],
            "acknowledgement_required": contract["authorization"]["acknowledgement"],
        },
        "evidence_scope": {
            "promotion_eligible": False,
            "background_vlm_verdict_observed": False,
        },
    }
    _validate(plan, _json(PLAN_SCHEMA_PATH))
    return plan


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class NoProxyNoRedirectOpener:
    """Explicit urllib adapter satisfying runtime-evidence-common policy."""

    proxies_enabled = False
    redirects_enabled = False

    def __init__(self, opener: OpenerDirector) -> None:
        self._opener = opener

    def open(self, request: Request, timeout: float) -> Any:
        try:
            return self._opener.open(request, timeout=timeout)
        except HTTPError as response:
            return response


def live_opener() -> NoProxyNoRedirectOpener:
    """Construct an explicit empty-proxy, redirect-rejecting opener; no I/O."""
    return NoProxyNoRedirectOpener(build_opener(ProxyHandler({}), _NoRedirect()))


def _media_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise CollectorError("configuration_error")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise CollectorError("configuration_error") from exc
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or port is None
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith((".mp4", ".mkv"))
    ):
        raise CollectorError("configuration_error")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise CollectorError("configuration_error") from exc
    if not address.is_loopback or "%" in parsed.hostname:
        raise CollectorError("configuration_error")
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    origin = f"http://{host}:{port}"
    try:
        admitted = common.LoopbackTarget.admit(origin, [parsed.path])
        path = admitted.admit_path(parsed.path)
    except common.EvidenceCommonError as exc:
        raise CollectorError("configuration_error") from exc
    canonical = admitted.origin + path
    if canonical != value:
        raise CollectorError("configuration_error")
    return canonical


def _response_json(result: Any, label: str) -> dict[str, Any]:
    if result.media_type != "application/json":
        raise CollectorError("invalid_response")
    try:
        return common.strict_json(result.body, label)
    except common.EvidenceCommonError as exc:
        raise CollectorError("invalid_response") from exc


def _configs(result: Any) -> list[dict[str, Any]]:
    if result.status != 200:
        raise CollectorError("oracle_failed")
    body = _response_json(result, "config-list")
    configs = body.get("configs")
    if (
        body.get("status") != "success"
        or not isinstance(configs, list)
        or body.get("count") != len(configs)
    ):
        raise CollectorError("oracle_failed")
    if any(
        not isinstance(item, dict) or not isinstance(item.get("alert_type"), str)
        for item in configs
    ):
        raise CollectorError("oracle_failed")
    names = [item["alert_type"] for item in configs]
    if len(names) != len(set(names)):
        raise CollectorError("oracle_failed")
    return sorted(configs, key=lambda item: item["alert_type"])


def _record(recorder: Any, action_id: str, kind: str, result: Any, code: str) -> None:
    recorder.record(
        action_id=action_id,
        kind=kind,
        status="pass",
        payload=result.body,
        result_code=code,
    )


def _is_exact_owned_config(
    value: dict[str, Any], expected: dict[str, Any], ownership_marker: str
) -> bool:
    """Require the complete persisted identity before admitting cleanup ownership."""
    if not isinstance(value, dict) or value.get("output_category") != ownership_marker:
        return False
    identity_fields = {
        "alert_type",
        "prompt",
        "system_prompt",
        "output_category",
        "vlm_params",
    }
    return all(value.get(field) == expected[field] for field in identity_fields)


def run_collector(
    *,
    run_id: str,
    acknowledgement: str,
    origin: str,
    media_url: str,
    opener_factory: Callable[[], Any],
) -> dict[str, Any]:
    plan = compile_plan()
    contract = _contract()
    if not isinstance(run_id, str) or not PLAIN_ID_RE.fullmatch(run_id):
        raise CollectorError("authorization_required")
    guard = common.RunAuthorizationGuard.from_token(
        run_id=run_id,
        authorization_id=contract["authorization"]["authorization_id"],
        authorization_token=contract["authorization"]["acknowledgement"],
    )
    try:
        identity = guard.admit(
            run_id=run_id,
            authorization_id=contract["authorization"]["authorization_id"],
            authorization_token=acknowledgement,
        )
    except common.EvidenceCommonError as exc:
        raise CollectorError("authorization_required") from exc

    media_url = _media_url(media_url)
    suffix = hashlib.sha256(run_id.encode()).hexdigest()[:16]
    alert_type = f"vss_oracle_candidate_{suffix}"
    missing_type = f"vss_oracle_missing_{suffix}"
    exact_path = f"/api/v1/verification/config/{alert_type}"
    allowed_paths = [*contract["target"]["paths"], exact_path]
    try:
        target = common.LoopbackTarget.admit(origin, allowed_paths)
    except common.EvidenceCommonError as exc:
        raise CollectorError("configuration_error") from exc
    if not callable(opener_factory):
        raise CollectorError("configuration_error")
    opener = opener_factory()
    bounds = contract["execution_bounds"]
    budget = common.ExecutionBudget(max_requests=8, max_actions=8)
    try:
        transport = common.BoundedHTTPTransport(
            target=target,
            opener=opener,
            budget=budget,
            max_request_bytes=bounds["max_request_bytes"],
            max_response_bytes=bounds["max_response_bytes"],
            timeout_seconds=bounds["timeout_seconds"],
        )
    except common.EvidenceCommonError as exc:
        raise CollectorError("configuration_error") from exc
    recorder = common.EvidenceRecorder(budget)
    ledger = common.ResourceLedger(identity, budget, max_resources=1)
    accepted, rejected, fixture_sha = _validate_fixture(contract)
    prompt = (
        "Return yes only when the candidate alert is visible in the supplied media."
    )
    ownership_marker = (
        "vss-oracle-owner-"
        + hashlib.sha256(
            common.canonical_bytes(
                {
                    "authorization_token_sha256": identity.authorization_token_sha256,
                    "collector_id": contract["collector_id"],
                    "run_id": run_id,
                    "resource_id": alert_type,
                }
            )
        ).hexdigest()[:32]
    )
    expected_config = {
        "alert_type": alert_type,
        "prompt": prompt,
        "system_prompt": "Answer only yes or no.",
        "output_category": ownership_marker,
        "vlm_params": {
            "num_frames": 4,
            "temperature": 0.0,
            "max_tokens": 32,
        },
    }
    config_payload = common.canonical_bytes(expected_config)
    pre_configs: list[dict[str, Any]] = []
    post_configs: list[dict[str, Any]] = []
    observations = {
        "health": "fail",
        "pre_state_owned_absent": False,
        "config_created": False,
        "config_identity": False,
        "positive_admitted": False,
        "adjacent_rejected": False,
        "cleanup_complete": False,
        "non_owned_state_restored": False,
    }

    def cleanup(exact: str) -> None:
        result = transport.request("DELETE", f"/api/v1/verification/config/{exact}")
        body = _response_json(result, "cleanup-delete")
        if result.status not in {200, 404}:
            raise CollectorError("cleanup_failed")
        if result.status == 200 and body.get("status") != "success":
            raise CollectorError("cleanup_failed")

    def postcondition(exact: str) -> bool:
        nonlocal post_configs
        result = transport.request("GET", "/api/v1/verification/config")
        post_configs = _configs(result)
        return all(
            item["alert_type"] != exact for item in post_configs
        ) and common.digest_value(pre_configs) == common.digest_value(post_configs)

    primary: BaseException | None = None
    try:
        health = transport.request("GET", "/health")
        health_body = _response_json(health, "health-response")
        if health.status != 200 or health_body.get("status") != "ok":
            raise CollectorError("oracle_failed")
        observations["health"] = "ok"
        _record(recorder, "health", "http-get", health, "service_healthy")

        pre = transport.request("GET", "/api/v1/verification/config")
        pre_configs = _configs(pre)
        if any(item["alert_type"] == alert_type for item in pre_configs):
            raise CollectorError("oracle_failed")
        observations["pre_state_owned_absent"] = True
        _record(recorder, "pre-state", "http-get", pre, "owned_absent")

        created = transport.request(
            "POST",
            "/api/v1/verification/config",
            body=config_payload,
            media_type="application/json",
        )
        created_body = _response_json(created, "create-config")
        if created.status != 201 or not _is_exact_owned_config(
            created_body, expected_config, ownership_marker
        ):
            raise CollectorError("oracle_failed")
        observations["config_created"] = True
        _record(recorder, "create-config", "http-post", created, "exact_config_created")

        inspected = transport.request("GET", exact_path)
        inspected_body = _response_json(inspected, "inspect-config")
        if inspected.status != 200 or not _is_exact_owned_config(
            inspected_body, expected_config, ownership_marker
        ):
            raise CollectorError("oracle_failed")
        # Ownership is admitted only after an unambiguous successful create and
        # a separate exact readback of the unique run-bound marker. A timeout,
        # redirect, 409, malformed 201, or concurrent winner leaves the ledger
        # empty, so this collector cannot delete a resource it did not prove.
        ledger.register(
            owner_run_id=run_id,
            resource_type="alert-verification-config",
            resource_id=alert_type,
            cleanup=cleanup,
            postcondition=postcondition,
        )
        observations["config_identity"] = True
        _record(recorder, "inspect-config", "http-get", inspected, "config_identity")

        positive_id = f"{accepted['alert_id']}-{suffix}"
        positive = transport.request(
            "POST",
            "/api/v1/verification/ondemand",
            body=common.canonical_bytes(
                {
                    "id": positive_id,
                    "sensorId": accepted["sensor_id"],
                    "category": alert_type,
                    "info": {"media_urls": [media_url], "media_type": "video"},
                }
            ),
            media_type="application/json",
        )
        positive_body = _response_json(positive, "positive-admission")
        if (
            positive.status != 202
            or positive_body.get("status") != "accepted"
            or positive_body.get("correlationId") != positive_id
        ):
            raise CollectorError("oracle_failed")
        observations["positive_admitted"] = True
        _record(recorder, "positive", "http-post", positive, "accepted_202")

        adjacent = transport.request(
            "POST",
            "/api/v1/verification/ondemand",
            body=common.canonical_bytes(
                {
                    "id": f"{rejected['alert_id']}-{suffix}",
                    "sensorId": rejected["sensor_id"],
                    "category": missing_type,
                    "info": {"media_urls": [media_url], "media_type": "video"},
                }
            ),
            media_type="application/json",
        )
        adjacent_body = _response_json(adjacent, "adjacent-rejection")
        if (
            adjacent.status != 400
            or adjacent_body.get("status") != "error"
            or adjacent_body.get("error") != "unknown_category"
        ):
            raise CollectorError("oracle_failed")
        observations["adjacent_rejected"] = True
        _record(
            recorder, "adjacent-negative", "http-post", adjacent, "unknown_category_400"
        )
    except BaseException as exc:
        primary = exc
    finally:
        if ledger.active_count:
            try:
                cleaned = ledger.cleanup()
            except common.EvidenceCommonError:
                cleaned = False
            observations["cleanup_complete"] = cleaned and ledger.active_count == 0
            observations["non_owned_state_restored"] = cleaned and common.digest_value(
                pre_configs
            ) == common.digest_value(post_configs)

    if primary is not None:
        if isinstance(primary, CollectorError):
            raise primary
        if isinstance(primary, common.EvidenceCommonError):
            raise CollectorError("transport_error") from primary
        raise CollectorError("oracle_failed") from primary
    if (
        not observations["cleanup_complete"]
        or not observations["non_owned_state_restored"]
    ):
        raise CollectorError("cleanup_failed")
    comparison = common.DigestComparison.compare(
        "non-owned-configs", pre_configs, post_configs
    )
    runtime_evidence = recorder.build(
        identity=identity,
        ledger=ledger,
        comparisons=[comparison],
    )
    result = {
        "schema_version": 1,
        "collector_id": contract["collector_id"],
        "planning_requirement_id": contract["planning_requirement_id"],
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "status": runtime_evidence["status"],
        "promotion_eligible": False,
        "contract_sha256": plan["contract_sha256"],
        "fixture_sha256": fixture_sha,
        "target_origin_sha256": hashlib.sha256(target.origin.encode()).hexdigest(),
        "media_url_sha256": hashlib.sha256(media_url.encode()).hexdigest(),
        "accepted_alert_sha256": common.digest_value(accepted),
        "rejected_alert_sha256": common.digest_value(rejected),
        "observations": observations,
        "runtime_evidence": runtime_evidence,
    }
    _validate(result, _json(EVIDENCE_SCHEMA_PATH))
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan", help="compile the inert plan (default)")
    execute = subparsers.add_parser(
        "execute", help="run the authorized bounded collector"
    )
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--acknowledgement", required=True)
    execute.add_argument("--origin", default="http://127.0.0.1:9080")
    execute.add_argument("--media-url", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in {None, "plan"}:
            result = compile_plan()
        else:
            result = run_collector(
                run_id=args.run_id,
                acknowledgement=args.acknowledgement,
                origin=args.origin,
                media_url=args.media_url,
                opener_factory=live_opener,
            )
    except (CollectorError, common.EvidenceCommonError) as exc:
        code = exc.code if hasattr(exc, "code") else "configuration_error"
        print(json.dumps({"status": "fail", "error": code}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
