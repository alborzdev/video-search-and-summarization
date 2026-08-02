#!/usr/bin/env python3
"""Close Base semantic gaps with an exact fixture and object-store snapshots."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time
from typing import Any, Callable, Sequence

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT = HERE / "contract.json"
CONTRACT_SCHEMA = HERE / "contract.schema.json"
MANIFEST_SCHEMA = HERE / "request-manifest.schema.json"
RECEIPT_SCHEMA = HERE / "receipt.schema.json"
OBJECT_STORE_ROOT = ROOT / "deploy/docker/data-dir/agent-reports"


class ClosureError(RuntimeError):
    CODES = {
        "authorization_required",
        "configuration_error",
        "fixture_error",
        "invalid_manifest",
        "invalid_receipt",
        "oracle_failed",
        "snapshot_error",
        "transport_error",
    }

    def __init__(self, code: str):
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _load_predecessor():
    path = HERE.parent / "base-semantic-full-envelope-successor" / "executor.py"
    spec = importlib.util.spec_from_file_location(
        "base_owned_fixture_predecessor", path
    )
    if spec is None or spec.loader is None:
        raise ClosureError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


full = _load_predecessor()
common = full.common


def _raw(path: Path, maximum: int = 200_000_000) -> bytes:
    try:
        observed = path.lstat()
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_size <= 0
            or observed.st_size > maximum
        ):
            raise ClosureError("configuration_error")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            before = os.fstat(descriptor)
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                block = os.read(descriptor, min(remaining, 65_536))
                if not block:
                    raise ClosureError("configuration_error")
                chunks.append(block)
                remaining -= len(block)
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ClosureError("configuration_error")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    except ClosureError:
        raise
    except OSError as exc:
        raise ClosureError("configuration_error") from exc


def _json(path: Path, code: str = "configuration_error") -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ClosureError(code)
            result[key] = value
        return result

    try:
        value = json.loads(
            _raw(path, 50_000_000).decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ClosureError(code)),
        )
    except ClosureError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClosureError(code) from exc
    if not isinstance(value, dict):
        raise ClosureError(code)
    return value


def _validate(value: Any, schema_path: Path, code: str) -> None:
    try:
        schema = _json(schema_path)
        Draft202012Validator.check_schema(schema)
        if list(Draft202012Validator(schema).iter_errors(value)):
            raise ClosureError(code)
    except ClosureError:
        raise
    except Exception as exc:
        raise ClosureError("configuration_error") from exc


def _repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ClosureError("configuration_error")
    candidate = ROOT
    for part in pure.parts:
        candidate /= part
        try:
            if stat.S_ISLNK(candidate.lstat().st_mode):
                raise ClosureError("configuration_error")
        except ClosureError:
            raise
        except OSError as exc:
            raise ClosureError("configuration_error") from exc
    return candidate


def _contract() -> dict[str, Any]:
    value = _json(CONTRACT)
    _validate(value, CONTRACT_SCHEMA, "configuration_error")
    if (
        value["authorization"]
        != {
            "authorization_id": "base-semantic-owned-fixture",
            "acknowledgement": "I_ACK_BASE_OWNED_FIXTURE_LOCAL_RUNTIME",
        }
        or [row["case_id"] for row in value["cases"]]
        != ["tiny-agent-media", "hitl-state-transcript"]
        or value["object_store"]["host_root"] != "deploy/docker/data-dir/agent-reports"
    ):
        raise ClosureError("configuration_error")
    return value


def compile_plan() -> dict[str, Any]:
    contract = _contract()
    for lock in contract["source_locks"]:
        if hashlib.sha256(_raw(_repo_path(lock["path"]))).hexdigest() != lock["sha256"]:
            raise ClosureError("configuration_error")

    fixture = contract["fixture"]
    primary = _raw(
        _repo_path(fixture["primary_media_path"]), fixture["primary_media_bytes"]
    )
    if (
        len(primary) != fixture["primary_media_bytes"]
        or hashlib.sha256(primary).hexdigest() != fixture["primary_media_sha256"]
    ):
        raise ClosureError("configuration_error")

    compose = _raw(_repo_path("deploy/docker/thor-local/compose.yml")).decode()
    profile = _raw(
        _repo_path(
            "deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml"
        )
    ).decode()
    store = _raw(
        _repo_path("services/agent/src/vss_agents/tools/filesystem_object_store.py")
    ).decode()
    adapter = _raw(
        _repo_path(
            "deploy/docker/thor-local/qualification/candidate-oracle-adapter/adapter.json"
        )
    ).decode()
    required_adapter_semantics = (
        "Answer a pixel-dependent question about the selected clip",
        "excluding a planted visual distractor",
        "Populate required report sections with the beginning and ending fixture events and no absent event.",
    )
    if (
        "${VSS_DATA_DIR}/agent-reports:/vss-agent/agent_reports:rw" not in compose
        or "root_path: /vss-agent/agent_reports" not in profile
        or "if not await asyncio.to_thread(path.is_file)" not in store
        or "await asyncio.to_thread(path.unlink)" not in store
        or any(item not in adapter for item in required_adapter_semantics)
    ):
        raise ClosureError("configuration_error")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "inert-plan",
        "status": "pass",
        "runtime_actions": 0,
        "default_execution_enabled": False,
        "primary_pixel_fixture_materialized": True,
        "secondary_mkv_fixture_requires_reviewed_manifest": True,
        "object_store_snapshot_executor_ready": True,
        "preexisting_exact_pair_absence_observable": True,
        "dedicated_empty_report_store_required": True,
        "negative_request_report_delta_observable": True,
        "semantic_oracles_ready": True,
        "agent_media_digest_readback_proven": False,
        "canonical_binding": False,
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
        "contract_sha256": hashlib.sha256(_raw(CONTRACT)).hexdigest(),
    }


def _bounded_fixture(path_text: str, expected_sha: str, expected_size: int) -> None:
    path = Path(path_text)
    if not path.is_absolute() or path.suffix.casefold() != ".mkv":
        raise ClosureError("invalid_manifest")
    try:
        raw = _raw(path, expected_size)
    except ClosureError as exc:
        raise ClosureError("fixture_error") from exc
    if (
        len(raw) != expected_size
        or hashlib.sha256(raw).hexdigest() != expected_sha
        or not raw.startswith(b"\x1a\x45\xdf\xa3")
    ):
        raise ClosureError("fixture_error")


def _snapshot_digest(snapshot: dict[str, tuple[str, str | None, int]]) -> str:
    return hashlib.sha256(common.canonical_bytes(snapshot)).hexdigest()


class ReportSnapshotter:
    """Bounded, read-only inventory of report objects and sidecar metadata."""

    def __init__(self, root: Path, bounds: dict[str, Any]):
        self.root = root
        self.bounds = bounds

    def _hash_file(self, path: Path, maximum: int) -> tuple[str, int]:
        raw = _raw(path, maximum)
        return hashlib.sha256(raw).hexdigest(), len(raw)

    def capture(self) -> dict[str, tuple[str, str | None, int]]:
        try:
            root = self.root.resolve(strict=True)
            expected = OBJECT_STORE_ROOT.resolve(strict=True)
        except OSError as exc:
            raise ClosureError("snapshot_error") from exc
        if root != expected or not root.is_dir():
            raise ClosureError("snapshot_error")

        candidates: list[tuple[str, Path]] = []
        sidecars: dict[str, Path] = {}

        def classify(relative: str, path: Path, mode: int) -> None:
            if full.exact.KEY.fullmatch(relative):
                if not stat.S_ISREG(mode):
                    raise ClosureError("snapshot_error")
                candidates.append((relative, path))
                return
            name = Path(relative).name
            if name.startswith(".") and name.endswith(".vss-object.json"):
                object_name = name[1 : -len(".vss-object.json")]
                parent = Path(relative).parent
                object_key = (
                    object_name
                    if parent == Path(".")
                    else (parent / object_name).as_posix()
                )
                if full.exact.KEY.fullmatch(object_key):
                    if not stat.S_ISREG(mode) or object_key in sidecars:
                        raise ClosureError("snapshot_error")
                    sidecars[object_key] = path

        try:
            for item in root.iterdir():
                observed = item.lstat()
                if stat.S_ISDIR(observed.st_mode):
                    for child in item.iterdir():
                        child_stat = child.lstat()
                        relative = f"{item.name}/{child.name}"
                        classify(relative, child, child_stat.st_mode)
                else:
                    classify(item.name, item, observed.st_mode)
        except (OSError, ClosureError) as exc:
            if isinstance(exc, ClosureError):
                raise
            raise ClosureError("snapshot_error") from exc

        if len(candidates) > self.bounds["max_report_objects"]:
            raise ClosureError("snapshot_error")
        total = 0
        result: dict[str, tuple[str, str | None, int]] = {}
        for key, path in sorted(candidates):
            digest, size = self._hash_file(path, self.bounds["max_report_object_bytes"])
            total += size
            metadata = sidecars.pop(key, None)
            metadata_digest = None
            if metadata is not None:
                metadata_digest, metadata_size = self._hash_file(
                    metadata, self.bounds["max_metadata_bytes"]
                )
                total += metadata_size
            if total > self.bounds["max_total_snapshot_bytes"]:
                raise ClosureError("snapshot_error")
            result[key] = (digest, metadata_digest, size)
        for key, metadata in sorted(sidecars.items()):
            digest, size = self._hash_file(metadata, self.bounds["max_metadata_bytes"])
            total += size
            if total > self.bounds["max_total_snapshot_bytes"]:
                raise ClosureError("snapshot_error")
            result[f"@orphan-metadata/{key}"] = (digest, None, size)
        return result


class BufferedResponse:
    def __init__(self, original: Any, body: bytes):
        self.status = original.status
        self.headers = original.headers
        self._url = original.geturl()
        self._body = body
        self._original = original

    def geturl(self):
        return self._url

    def read(self, size=-1):
        return self._body if size < 0 else self._body[:size]

    def close(self):
        self._original.close()


class SemanticGuardOpener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(
        self,
        opener: Any,
        manifest: dict[str, Any],
        case: dict[str, Any],
        contract: dict[str, Any],
        allowed_origins: set[tuple[str, str]],
        snapshotter: ReportSnapshotter,
        quiescence_waiter: Callable[[float], None],
    ):
        self.opener = opener
        self.manifest = manifest
        self.case = case
        self.contract = contract
        self.allowed_origins = allowed_origins
        self.snapshotter = snapshotter
        self.quiescence_waiter = quiescence_waiter
        self.semantic_index = 0
        self.failure: ClosureError | None = None
        self.pre = snapshotter.capture()
        if self.pre:
            self._fail("snapshot_error")
        self.pair: tuple[str, str] | None = None
        self.vqa_verified: list[str] = []
        self.negative_verified: list[str] = []
        self.report_verified = False

    def _fail(self, code: str) -> None:
        self.failure = ClosureError(code)
        raise self.failure

    def _assert_terms(
        self,
        raw: bytes,
        required: list[str],
        forbidden: list[str],
        forbidden_all: list[list[str]] | None = None,
    ) -> None:
        try:
            text = raw.decode("utf-8").casefold()
        except UnicodeDecodeError:
            self._fail("oracle_failed")
        if (
            any(item.casefold() not in text for item in required)
            or any(item.casefold() in text for item in forbidden)
            or any(
                all(term.casefold() in text for term in group)
                for group in (forbidden_all or [])
            )
        ):
            self._fail("oracle_failed")

    def _assert_groups(
        self,
        raw: bytes,
        required_any: list[list[str]],
        forbidden_all: list[list[str]],
    ) -> None:
        try:
            text = raw.decode("utf-8").casefold()
        except UnicodeDecodeError:
            self._fail("oracle_failed")
        if any(
            not any(alternative.casefold() in text for alternative in group)
            for group in required_any
        ) or any(
            all(term.casefold() in text for term in group) for group in forbidden_all
        ):
            self._fail("oracle_failed")

    def open(self, request: Any, timeout: int):
        operation = None
        before_negative = None
        if request.method == "POST":
            if self.semantic_index >= len(self.manifest["operations"]):
                self._fail("transport_error")
            operation = self.manifest["operations"][self.semantic_index]
            self.semantic_index += 1
            if operation["step_id"] in self.case["negative_steps"]:
                before_negative = self.snapshotter.capture()
        original = self.opener.open(request, timeout)
        try:
            raw = original.read(
                self.contract["object_store"]["max_report_object_bytes"] + 1
            )
        except Exception:
            original.close()
            self._fail("transport_error")
        buffered = BufferedResponse(original, raw)
        if operation is not None:
            step = operation["step_id"]
            if step in self.case["vqa_steps"]:
                facts = self.contract["fixture"]["pixel_facts"][step]
                self._assert_terms(
                    raw,
                    facts["required"],
                    facts["forbidden"],
                    facts["forbidden_all"],
                )
                self.vqa_verified.append(step)
            if step == self.case["report_step_id"]:
                try:
                    pair = full._candidate_pair(raw, self.allowed_origins)
                except full.EnvelopeError:
                    self._fail("oracle_failed")
                if pair is None:
                    self._fail("oracle_failed")
                keys = [path.removeprefix("/static/") for path in pair]
                if any(key in self.pre for key in keys):
                    self._fail("oracle_failed")
                self.pair = pair
            if step == "cancel":
                self._assert_terms(raw, ["cancel"], [])
                if full._candidate_pair(raw, self.allowed_origins) is not None:
                    self._fail("oracle_failed")
            if before_negative is not None:
                immediate = self.snapshotter.capture()
                self.quiescence_waiter(
                    self.contract["object_store"]["negative_quiescence_seconds"]
                )
                after_quiescence = self.snapshotter.capture()
                if immediate != before_negative or after_quiescence != before_negative:
                    self._fail("oracle_failed")
                self.negative_verified.append(step)
        elif (
            request.method == "GET"
            and self.pair is not None
            and request.full_url.endswith(self.pair[0])
            and 200 <= original.status <= 299
        ):
            report = self.contract["fixture"]["report_semantics"]
            self._assert_groups(
                raw,
                [[section] for section in report["required_sections"]]
                + report["beginning_events"]
                + report["ending_events"],
                report["absent_events"],
            )
            self.report_verified = True
        return buffered


def _case(contract: dict[str, Any], case_id: str) -> dict[str, Any]:
    rows = [row for row in contract["cases"] if row["case_id"] == case_id]
    if len(rows) != 1:
        raise ClosureError("invalid_manifest")
    return rows[0]


def _manifest(
    value: dict[str, Any], case: dict[str, Any], contract: dict[str, Any], run_id: str
) -> set[tuple[str, str]]:
    _validate(value, MANIFEST_SCHEMA, "invalid_manifest")
    predecessor_value = {
        key: item for key, item in value.items() if key != "fixture_binding"
    }
    predecessor_case = _case(full._contract(), case["case_id"])
    try:
        allowed = full._manifest(predecessor_value, predecessor_case, run_id)
    except full.EnvelopeError as exc:
        raise ClosureError(exc.code) from exc

    fixture = contract["fixture"]
    binding = value["fixture_binding"]
    encoded_by_step = {
        row["step_id"]: common.canonical_bytes(row["body"])
        for row in value["operations"]
    }
    primary_token = fixture["primary_media_sha256"].encode()
    secondary_token = binding["secondary_sha256"].encode()
    required_body_bindings = {
        case["report_step_id"]: (
            fixture["primary_agent_media_id"].encode(),
            primary_token,
        )
    }
    if case["vqa_steps"]:
        required_body_bindings.update(
            {
                "qa-mp4": (
                    fixture["primary_agent_media_id"].encode(),
                    primary_token,
                ),
                "qa-mkv": (
                    fixture["secondary_agent_media_id"].encode(),
                    secondary_token,
                ),
                "followup-qa": (
                    fixture["primary_agent_media_id"].encode(),
                    primary_token,
                ),
            }
        )
    for step, tokens in required_body_bindings.items():
        body = encoded_by_step.get(step, b"")
        if any(token not in body for token in tokens):
            raise ClosureError("invalid_manifest")

    leaked: list[str] = []
    for step in case["vqa_steps"]:
        body = encoded_by_step[step].decode("utf-8").casefold()
        leaked.extend(
            item
            for item in fixture["pixel_facts"][step]["required"]
            if item.casefold() in body
        )
    report_body = encoded_by_step[case["report_step_id"]].decode("utf-8").casefold()
    report = fixture["report_semantics"]
    leaked.extend(
        item
        for group in report["beginning_events"] + report["ending_events"]
        for item in group
        if item.casefold() in report_body
    )
    if leaked:
        raise ClosureError("invalid_manifest")
    return allowed


def execute_http(
    *,
    manifest: dict[str, Any],
    run_id: str,
    acknowledgement: str,
    origin: str,
    opener_factory: Callable[[], Any] = full.base.LiveOpener,
    snapshotter_factory: Callable[
        [Path, dict[str, Any]], ReportSnapshotter
    ] = ReportSnapshotter,
    quiescence_waiter: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    plan, contract = compile_plan(), _contract()
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise ClosureError("authorization_required")
    case = _case(contract, manifest.get("case_id", ""))
    allowed_origins = _manifest(manifest, case, contract, run_id)
    binding = manifest["fixture_binding"]
    _bounded_fixture(
        binding["secondary_local_path"],
        binding["secondary_sha256"],
        binding["secondary_bytes"],
    )
    snapshotter = snapshotter_factory(OBJECT_STORE_ROOT, contract["object_store"])
    guard = SemanticGuardOpener(
        opener_factory(),
        manifest,
        case,
        contract,
        allowed_origins,
        snapshotter,
        quiescence_waiter,
    )
    predecessor_manifest = {
        key: value for key, value in manifest.items() if key != "fixture_binding"
    }
    try:
        predecessor_receipt = full.execute_http(
            manifest=predecessor_manifest,
            run_id=run_id,
            acknowledgement="I_ACK_BASE_FULL_ENVELOPE_LOCAL_RUNTIME",
            origin=origin,
            opener_factory=lambda: guard,
        )
    except full.EnvelopeError as exc:
        if guard.failure is not None:
            raise guard.failure from exc
        raise ClosureError(exc.code) from exc

    post = snapshotter.capture()
    if (
        guard.pair is None
        or not guard.report_verified
        or guard.vqa_verified != case["vqa_steps"]
        or guard.negative_verified != case["negative_steps"]
        or post != guard.pre
    ):
        raise ClosureError("oracle_failed")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "bounded-http-owned-fixture-candidate",
        "status": "semantic_closure_candidate_complete_non_promoting",
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "case_id": case["case_id"],
        "contract_sha256": plan["contract_sha256"],
        "manifest_sha256": hashlib.sha256(common.canonical_bytes(manifest)).hexdigest(),
        "predecessor_receipt_sha256": hashlib.sha256(
            common.canonical_bytes(predecessor_receipt)
        ).hexdigest(),
        "fixture": {
            "fixture_id": contract["fixture"]["fixture_id"],
            "primary_sha256": contract["fixture"]["primary_media_sha256"],
            "primary_bytes": contract["fixture"]["primary_media_bytes"],
            "secondary_sha256": binding["secondary_sha256"],
            "secondary_bytes": binding["secondary_bytes"],
            "primary_local_bytes_verified": True,
            "secondary_local_bytes_verified": True,
            "agent_media_ids_request_bound": True,
            "agent_media_digest_readback_proven": False,
        },
        "semantics": {
            "vqa_steps_verified": guard.vqa_verified,
            "report_sections_verified": True,
            "beginning_events_verified": True,
            "ending_events_verified": True,
            "absent_events_excluded": True,
            "negative_steps_no_report_delta": guard.negative_verified,
            "semantic_values_request_leakage_rejected": True,
        },
        "object_store": {
            "root_sha256": hashlib.sha256(str(OBJECT_STORE_ROOT).encode()).hexdigest(),
            "pre_snapshot_sha256": _snapshot_digest(guard.pre),
            "post_snapshot_sha256": _snapshot_digest(post),
            "pre_report_object_count": len(guard.pre),
            "preexisting_report_pair_absence_proven": True,
            "exact_pair_only_removed": True,
            "post_snapshot_equals_pre_snapshot": True,
            "foreign_report_objects_mutated": False,
            "snapshot_complete_within_bounds": True,
            "negative_quiescence_seconds": contract["object_store"][
                "negative_quiescence_seconds"
            ],
        },
    }
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    _validate(receipt, RECEIPT_SCHEMA, "invalid_receipt")
    plan, contract = compile_plan(), _contract()
    case = _case(contract, receipt["case_id"])
    if (
        receipt["contract_sha256"] != plan["contract_sha256"]
        or receipt["semantics"]["vqa_steps_verified"] != case["vqa_steps"]
        or receipt["semantics"]["negative_steps_no_report_delta"]
        != case["negative_steps"]
        or receipt["object_store"]["pre_snapshot_sha256"]
        != receipt["object_store"]["post_snapshot_sha256"]
    ):
        raise ClosureError("invalid_receipt")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "candidate_receipt_valid_non_promoting",
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "receipt_sha256": hashlib.sha256(common.canonical_bytes(receipt)).hexdigest(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("plan")
    execute = sub.add_parser("execute-http")
    execute.add_argument("--manifest", type=Path, required=True)
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--acknowledgement", required=True)
    execute.add_argument("--origin", default="http://127.0.0.1:8000")
    validate = sub.add_parser("validate-receipt")
    validate.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "execute-http":
            result = execute_http(
                manifest=_json(args.manifest, "invalid_manifest"),
                run_id=args.run_id,
                acknowledgement=args.acknowledgement,
                origin=args.origin,
            )
        elif args.command == "validate-receipt":
            result = validate_receipt(_json(args.receipt, "invalid_receipt"))
        else:
            result = compile_plan()
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except ClosureError as exc:
        print(json.dumps({"status": "error", "code": exc.code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
