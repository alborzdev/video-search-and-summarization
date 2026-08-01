#!/usr/bin/env python3
"""Fail-closed primitives for future, explicitly authorized runtime evidence.

This module does not construct a network opener, run a subprocess, inspect the
host, or manage a service.  HTTP is reachable only through an opener injected
by a caller after all admission checks pass.  The command-line interface is
limited to static package validation and a fake-only self-test.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Protocol, Sequence
from urllib.parse import urlsplit
from urllib.request import Request

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
EVIDENCE_SCHEMA_PATH = HERE / "evidence.schema.json"
MAX_PACKAGE_BYTES = 1024 * 1024
PLAIN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
RESULT_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
ALLOWED_METHODS = {"DELETE", "GET", "PATCH", "POST", "PUT"}


class EvidenceCommonError(RuntimeError):
    """Base error carrying only a stable, non-secret public code."""

    _CODES = {
        "action_budget_exceeded",
        "authorization_mismatch",
        "cleanup_failed",
        "configuration_error",
        "identity_mismatch",
        "invalid_evidence",
        "invalid_path",
        "invalid_response",
        "request_budget_exceeded",
        "request_too_large",
        "response_too_large",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self._CODES else "configuration_error"
        super().__init__(self.code)


class AdmissionError(EvidenceCommonError):
    """An identity, target, path, or policy failed before transport."""


class BudgetError(EvidenceCommonError):
    """A request or evidence action exceeded its declared bound."""


class TransportError(EvidenceCommonError):
    """The injected HTTP transport violated its declared bound or policy."""


class CleanupError(EvidenceCommonError):
    """Owned resources remain or a cleanup postcondition failed."""


def _plain_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not PLAIN_ID_RE.fullmatch(value):
        raise AdmissionError("configuration_error")
    return value


def _result_code(value: Any) -> str:
    if not isinstance(value, str) or not RESULT_CODE_RE.fullmatch(value):
        raise AdmissionError("configuration_error")
    return value


def canonical_bytes(value: Any) -> bytes:
    """Return bounded, deterministic JSON bytes; reject NaN and non-JSON data."""
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise AdmissionError("configuration_error") from exc
    if len(raw) > MAX_PACKAGE_BYTES:
        raise AdmissionError("configuration_error")
    return raw


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest_value(value: Any) -> str:
    """Digest state without admitting the state value into evidence."""
    return sha256_bytes(canonical_bytes(value))


def strict_json(raw: bytes, label: str) -> dict[str, Any]:
    """Decode a bounded JSON object while rejecting duplicate keys and NaN."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_PACKAGE_BYTES:
        raise AdmissionError("configuration_error")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AdmissionError("configuration_error")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                AdmissionError("configuration_error")
            ),
        )
    except AdmissionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdmissionError("configuration_error") from exc
    if not isinstance(value, dict):
        raise AdmissionError("configuration_error")
    _plain_id(label, "label")
    return value


def validate_schema(instance: Any, schema: dict[str, Any]) -> None:
    """Validate with Draft 2020-12 and collapse details to a public code."""
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(instance))
    except SchemaError as exc:
        raise AdmissionError("configuration_error") from exc
    if errors:
        raise AdmissionError("invalid_evidence")


@dataclass(frozen=True)
class LoopbackTarget:
    """A canonical numeric-loopback origin plus an exact path allowlist."""

    origin: str
    allowed_paths: tuple[str, ...]

    @classmethod
    def admit(cls, origin: str, allowed_paths: Sequence[str]) -> "LoopbackTarget":
        if not isinstance(origin, str) or not origin or len(origin) > 256:
            raise AdmissionError("configuration_error")
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError as exc:
            raise AdmissionError("configuration_error") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or port is None
            or not 1 <= port <= 65535
            or parsed.hostname is None
            or "%" in parsed.hostname
        ):
            raise AdmissionError("configuration_error")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise AdmissionError("configuration_error") from exc
        if not address.is_loopback:
            raise AdmissionError("configuration_error")
        if not isinstance(allowed_paths, (list, tuple)) or not allowed_paths:
            raise AdmissionError("configuration_error")
        admitted: list[str] = []
        for path in allowed_paths:
            admitted.append(_admit_literal_path(path))
        if len(set(admitted)) != len(admitted):
            raise AdmissionError("configuration_error")
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
        return cls(
            origin=f"{parsed.scheme}://{host}:{port}",
            allowed_paths=tuple(admitted),
        )

    def admit_path(self, path: str) -> str:
        admitted = _admit_literal_path(path)
        if admitted not in self.allowed_paths:
            raise AdmissionError("invalid_path")
        return admitted


def _admit_literal_path(path: Any) -> str:
    if not isinstance(path, str) or not 1 <= len(path) <= 512:
        raise AdmissionError("invalid_path")
    if (
        not path.isascii()
        or not path.startswith("/")
        or path.startswith("//")
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in path)
    ):
        raise AdmissionError("invalid_path")
    if "\\" in path or "%" in path:
        raise AdmissionError("invalid_path")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise AdmissionError("invalid_path")
    segments = parsed.path.split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise AdmissionError("invalid_path")
    return parsed.path


@dataclass
class ExecutionBudget:
    """Monotonic request and action counters with immutable upper bounds."""

    max_requests: int
    max_actions: int
    requests: int = 0
    actions: int = 0

    def __post_init__(self) -> None:
        if (
            type(self.max_requests) is not int
            or type(self.max_actions) is not int
            or not 1 <= self.max_requests <= 64
            or not 1 <= self.max_actions <= 64
            or self.requests != 0
            or self.actions != 0
        ):
            raise AdmissionError("configuration_error")

    def consume_request(self) -> None:
        if self.requests >= self.max_requests:
            raise BudgetError("request_budget_exceeded")
        self.requests += 1

    def consume_action(self) -> None:
        self.consume_actions(1)

    def consume_actions(self, count: int) -> None:
        """Atomically reserve a positive number of action transitions."""
        if type(count) is not int or count < 1:
            raise AdmissionError("configuration_error")
        if self.actions + count > self.max_actions:
            raise BudgetError("action_budget_exceeded")
        self.actions += count

    def evidence(self) -> dict[str, int]:
        return {
            "actions": self.actions,
            "max_actions": self.max_actions,
            "requests": self.requests,
            "max_requests": self.max_requests,
        }


@dataclass(frozen=True)
class EvidenceIdentity:
    run_id: str
    authorization_id: str
    authorization_token_sha256: str

    def __post_init__(self) -> None:
        _plain_id(self.run_id, "run_id")
        _plain_id(self.authorization_id, "authorization_id")
        if not re.fullmatch(r"[0-9a-f]{64}", self.authorization_token_sha256):
            raise AdmissionError("configuration_error")

    def evidence(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "authorization_id": self.authorization_id,
            "authorization_token_sha256": self.authorization_token_sha256,
        }


@dataclass(frozen=True)
class RunAuthorizationGuard:
    """Bind a run to one exact approval identity without retaining its token."""

    expected_run_id: str
    expected_authorization_id: str
    expected_token_sha256: str

    def __post_init__(self) -> None:
        _plain_id(self.expected_run_id, "run_id")
        _plain_id(self.expected_authorization_id, "authorization_id")
        if not re.fullmatch(r"[0-9a-f]{64}", self.expected_token_sha256):
            raise AdmissionError("configuration_error")

    @classmethod
    def from_token(
        cls, *, run_id: str, authorization_id: str, authorization_token: str
    ) -> "RunAuthorizationGuard":
        if (
            not isinstance(authorization_token, str)
            or not 1 <= len(authorization_token) <= 4096
        ):
            raise AdmissionError("configuration_error")
        return cls(
            expected_run_id=run_id,
            expected_authorization_id=authorization_id,
            expected_token_sha256=sha256_bytes(authorization_token.encode("utf-8")),
        )

    def admit(
        self, *, run_id: str, authorization_id: str, authorization_token: str
    ) -> EvidenceIdentity:
        _plain_id(run_id, "run_id")
        _plain_id(authorization_id, "authorization_id")
        if (
            run_id != self.expected_run_id
            or authorization_id != self.expected_authorization_id
        ):
            raise AdmissionError("identity_mismatch")
        if not isinstance(authorization_token, str):
            raise AdmissionError("authorization_mismatch")
        actual = sha256_bytes(authorization_token.encode("utf-8"))
        if not hmac.compare_digest(actual, self.expected_token_sha256):
            raise AdmissionError("authorization_mismatch")
        return EvidenceIdentity(run_id, authorization_id, actual)


class OpenerResponse(Protocol):
    status: int
    headers: Any

    def read(self, size: int = -1) -> bytes: ...

    def geturl(self) -> str: ...

    def close(self) -> None: ...


class InjectedOpener(Protocol):
    proxies_enabled: bool
    redirects_enabled: bool

    def open(self, request: Request, timeout: float) -> OpenerResponse: ...


@dataclass(frozen=True)
class HTTPResult:
    status: int
    media_type: str
    body: bytes


class BoundedHTTPTransport:
    """Bounded HTTP over an explicitly supplied, policy-labelled opener."""

    def __init__(
        self,
        *,
        target: LoopbackTarget,
        opener: InjectedOpener,
        budget: ExecutionBudget,
        max_request_bytes: int = 2 * 1024 * 1024,
        max_response_bytes: int = 1024 * 1024,
        timeout_seconds: float = 10,
    ) -> None:
        if (
            not isinstance(target, LoopbackTarget)
            or LoopbackTarget.admit(target.origin, target.allowed_paths) != target
            or not isinstance(budget, ExecutionBudget)
            or opener is None
        ):
            raise AdmissionError("configuration_error")
        if (
            getattr(opener, "proxies_enabled", None) is not False
            or getattr(opener, "redirects_enabled", None) is not False
        ):
            raise AdmissionError("configuration_error")
        if (
            type(max_request_bytes) is not int
            or type(max_response_bytes) is not int
            or not 1 <= max_request_bytes <= 2 * 1024 * 1024
            or not 1 <= max_response_bytes <= 1024 * 1024
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 10
        ):
            raise AdmissionError("configuration_error")
        self._target = target
        self._opener = opener
        self._budget = budget
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._timeout_seconds = float(timeout_seconds)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        media_type: str | None = None,
    ) -> HTTPResult:
        if method not in ALLOWED_METHODS or not isinstance(body, bytes):
            raise AdmissionError("configuration_error")
        admitted_path = self._target.admit_path(path)
        if len(body) > self._max_request_bytes:
            raise TransportError("request_too_large")
        if media_type is not None and (
            not isinstance(media_type, str)
            or not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", media_type)
        ):
            raise AdmissionError("configuration_error")
        self._budget.consume_request()
        expected_url = self._target.origin + admitted_path
        headers = {
            "Accept": "application/json",
            "Content-Length": str(len(body)),
        }
        if media_type is not None:
            headers["Content-Type"] = media_type
        request = Request(
            expected_url, data=body or None, headers=headers, method=method
        )
        response: OpenerResponse | None = None
        try:
            response = self._opener.open(request, timeout=self._timeout_seconds)
            try:
                status = response.status
                final_url = response.geturl()
                length_header = response.headers.get("Content-Length")
                response_media_type = response.headers.get("Content-Type", "")
                if type(status) is not int or not 100 <= status <= 599:
                    raise TransportError("invalid_response")
                if 300 <= status <= 399 or final_url != expected_url:
                    raise TransportError("transport_error")
                if length_header is not None:
                    try:
                        declared_length = int(length_header)
                    except (TypeError, ValueError) as exc:
                        raise TransportError("invalid_response") from exc
                    if (
                        declared_length < 0
                        or declared_length > self._max_response_bytes
                    ):
                        raise TransportError("response_too_large")
                response_body = response.read(self._max_response_bytes + 1)
            finally:
                response.close()
        except EvidenceCommonError:
            raise
        except Exception as exc:
            raise TransportError("transport_error") from exc
        if not isinstance(response_body, bytes):
            raise TransportError("invalid_response")
        if len(response_body) > self._max_response_bytes:
            raise TransportError("response_too_large")
        response_media_type = response_media_type.split(";", 1)[0].strip().lower()
        return HTTPResult(
            status=status, media_type=response_media_type, body=response_body
        )


CleanupAction = Callable[[str], None]
CleanupPostcondition = Callable[[str], bool]


@dataclass(frozen=True)
class _OwnedResource:
    resource_type: str
    resource_id: str
    target_sha256: str
    cleanup: CleanupAction
    postcondition: CleanupPostcondition


class ResourceLedger:
    """An in-memory, exact-run-owned LIFO cleanup ledger.

    The exact resource identifier is supplied only to its registered cleanup
    and absence-postcondition callbacks.  Evidence contains its digest only.
    Cleanup stops on the first failure and retains that top entry for recovery.
    """

    def __init__(
        self,
        identity: EvidenceIdentity,
        budget: ExecutionBudget,
        *,
        max_resources: int = 64,
    ) -> None:
        if (
            not isinstance(identity, EvidenceIdentity)
            or not isinstance(budget, ExecutionBudget)
            or type(max_resources) is not int
            or not 1 <= max_resources <= 64
        ):
            raise AdmissionError("configuration_error")
        self._identity = identity
        self._budget = budget
        self._max_resources = max_resources
        self._stack: list[_OwnedResource] = []
        self._target_hashes: set[str] = set()
        self.records: list[dict[str, Any]] = []

    @property
    def active_count(self) -> int:
        return len(self._stack)

    def register(
        self,
        *,
        owner_run_id: str,
        resource_type: str,
        resource_id: str,
        cleanup: CleanupAction,
        postcondition: CleanupPostcondition,
    ) -> str:
        if owner_run_id != self._identity.run_id:
            raise AdmissionError("identity_mismatch")
        resource_type = _plain_id(resource_type, "resource_type")
        if not isinstance(resource_id, str) or not 1 <= len(resource_id) <= 1024:
            raise AdmissionError("configuration_error")
        if not callable(cleanup) or not callable(postcondition):
            raise AdmissionError("configuration_error")
        if len(self._stack) >= self._max_resources:
            raise BudgetError("action_budget_exceeded")
        target_sha = sha256_bytes(
            canonical_bytes(
                {
                    "owner_run_id": owner_run_id,
                    "resource_id": resource_id,
                    "resource_type": resource_type,
                }
            )
        )
        if target_sha in self._target_hashes:
            raise AdmissionError("configuration_error")
        self._stack.append(
            _OwnedResource(
                resource_type, resource_id, target_sha, cleanup, postcondition
            )
        )
        self._target_hashes.add(target_sha)
        return target_sha

    def cleanup(self) -> bool:
        while self._stack:
            resource = self._stack[-1]
            # Exact cleanup and its absence postcondition are two independently
            # counted transitions. Reserve both atomically before mutation so a
            # missing postcondition slot cannot strand an unverified mutation.
            self._budget.consume_actions(2)
            record: dict[str, Any] = {
                "order": len(self.records) + 1,
                "resource_type": resource.resource_type,
                "target_sha256": resource.target_sha256,
                "action_status": "fail",
                "postcondition_status": "not_run",
            }
            try:
                resource.cleanup(resource.resource_id)
                record["action_status"] = "pass"
            except Exception:
                self.records.append(record)
                return False
            try:
                absent = resource.postcondition(resource.resource_id)
            except Exception:
                absent = False
            record["postcondition_status"] = "pass" if absent is True else "fail"
            self.records.append(record)
            if absent is not True:
                return False
            self._stack.pop()
            self._target_hashes.remove(resource.target_sha256)
        return True

    def assert_postconditions(self) -> None:
        if self._stack or any(
            record["action_status"] != "pass"
            or record["postcondition_status"] != "pass"
            for record in self.records
        ):
            raise CleanupError("cleanup_failed")


@dataclass(frozen=True)
class DigestComparison:
    comparison_id: str
    pre_sha256: str
    post_sha256: str
    expectation: str
    status: str

    def __post_init__(self) -> None:
        _plain_id(self.comparison_id, "comparison_id")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", self.pre_sha256)
            or not re.fullmatch(r"[0-9a-f]{64}", self.post_sha256)
            or self.expectation not in {"equal", "different"}
            or self.status not in {"pass", "fail"}
        ):
            raise AdmissionError("configuration_error")
        matched = self.pre_sha256 == self.post_sha256
        expected_status = (
            "pass"
            if (matched if self.expectation == "equal" else not matched)
            else "fail"
        )
        if self.status != expected_status:
            raise AdmissionError("configuration_error")

    @classmethod
    def compare(
        cls,
        comparison_id: str,
        pre_state: Any,
        post_state: Any,
        *,
        expectation: str = "equal",
    ) -> "DigestComparison":
        comparison_id = _plain_id(comparison_id, "comparison_id")
        if expectation not in {"equal", "different"}:
            raise AdmissionError("configuration_error")
        pre_sha = digest_value(pre_state)
        post_sha = digest_value(post_state)
        matched = pre_sha == post_sha
        passed = matched if expectation == "equal" else not matched
        return cls(
            comparison_id,
            pre_sha,
            post_sha,
            expectation,
            "pass" if passed else "fail",
        )

    def evidence(self) -> dict[str, str]:
        return {
            "comparison_id": self.comparison_id,
            "pre_sha256": self.pre_sha256,
            "post_sha256": self.post_sha256,
            "expectation": self.expectation,
            "status": self.status,
        }


class EvidenceRecorder:
    """Record only stable labels and payload size/digest, never raw values."""

    def __init__(self, budget: ExecutionBudget) -> None:
        if not isinstance(budget, ExecutionBudget):
            raise AdmissionError("configuration_error")
        self._budget = budget
        self.actions: list[dict[str, Any]] = []

    def record(
        self,
        *,
        action_id: str,
        kind: str,
        status: str,
        payload: bytes = b"",
        result_code: str,
    ) -> None:
        action_id = _plain_id(action_id, "action_id")
        kind = _plain_id(kind, "kind")
        result_code = _result_code(result_code)
        if status not in {"pass", "fail"} or not isinstance(payload, bytes):
            raise AdmissionError("configuration_error")
        if len(payload) > 1024 * 1024:
            raise TransportError("response_too_large")
        self._budget.consume_action()
        self.actions.append(
            {
                "order": len(self.actions) + 1,
                "action_id": action_id,
                "kind": kind,
                "status": status,
                "payload_bytes": len(payload),
                "payload_sha256": sha256_bytes(payload),
                "result_code": result_code,
            }
        )

    def build(
        self,
        *,
        identity: EvidenceIdentity,
        ledger: ResourceLedger,
        comparisons: Sequence[DigestComparison],
    ) -> dict[str, Any]:
        if (
            not isinstance(identity, EvidenceIdentity)
            or ledger._identity != identity
            or ledger._budget is not self._budget
            or len(comparisons) > 64
            or any(not isinstance(item, DigestComparison) for item in comparisons)
        ):
            raise AdmissionError("configuration_error")
        failed = (
            ledger.active_count != 0
            or any(action["status"] != "pass" for action in self.actions)
            or any(
                record["action_status"] != "pass"
                or record["postcondition_status"] != "pass"
                for record in ledger.records
            )
            or any(item.status != "pass" for item in comparisons)
        )
        document = {
            "schema_version": 1,
            "package_id": "runtime-evidence-common",
            "status": "fail" if failed else "pass",
            "identity": identity.evidence(),
            "budget": self._budget.evidence(),
            "actions": list(self.actions),
            "cleanup": list(ledger.records),
            "comparisons": [item.evidence() for item in comparisons],
        }
        schema = _load_package_json(EVIDENCE_SCHEMA_PATH)
        validate_schema(document, schema)
        return document


def _load_package_json(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AdmissionError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 0 < before.st_size <= MAX_PACKAGE_BYTES
        ):
            raise AdmissionError("configuration_error")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_PACKAGE_BYTES:
            chunk = os.read(descriptor, min(131072, MAX_PACKAGE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, field) != getattr(after, field) for field in stable_fields
        ):
            raise AdmissionError("configuration_error")
    finally:
        os.close(descriptor)
    return strict_json(raw, path.stem.replace(".", "-"))


def check_package() -> dict[str, Any]:
    """Validate only immutable package files; perform no runtime operation."""
    contract = _load_package_json(CONTRACT_PATH)
    contract_schema = _load_package_json(CONTRACT_SCHEMA_PATH)
    evidence_schema = _load_package_json(EVIDENCE_SCHEMA_PATH)
    validate_schema(contract, contract_schema)
    try:
        Draft202012Validator.check_schema(evidence_schema)
    except SchemaError as exc:
        raise AdmissionError("configuration_error") from exc
    return {
        "schema_version": 1,
        "package_id": "runtime-evidence-common",
        "mode": "static-check",
        "status": "pass",
        "runtime_actions": 0,
    }


class _FakeResponse:
    def __init__(self, url: str, body: bytes) -> None:
        self.status = 200
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        }
        self._url = url
        self._body = body
        self.closed = False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def close(self) -> None:
        self.closed = True


class _FakeOpener:
    proxies_enabled = False
    redirects_enabled = False

    def open(self, request: Request, timeout: float) -> _FakeResponse:
        del timeout
        return _FakeResponse(request.full_url, b'{"fake":true}')


def fake_self_test() -> dict[str, Any]:
    """Exercise all primitives using in-memory fakes only."""
    guard = RunAuthorizationGuard.from_token(
        run_id="fake-run",
        authorization_id="fake-authorization",
        authorization_token="fake",
    )
    identity = guard.admit(
        run_id="fake-run",
        authorization_id="fake-authorization",
        authorization_token="fake",
    )
    budget = ExecutionBudget(max_requests=1, max_actions=3)
    target = LoopbackTarget.admit("http://127.0.0.1:1", ["/fake"])
    result = BoundedHTTPTransport(
        target=target, opener=_FakeOpener(), budget=budget
    ).request("GET", "/fake")
    recorder = EvidenceRecorder(budget)
    recorder.record(
        action_id="fake-action",
        kind="fake-http",
        status="pass",
        payload=result.body,
        result_code="fake_only",
    )
    owned = {"fake-resource"}
    ledger = ResourceLedger(identity, budget)
    ledger.register(
        owner_run_id="fake-run",
        resource_type="fake-resource",
        resource_id="fake-resource",
        cleanup=lambda resource_id: owned.discard(resource_id),
        postcondition=lambda resource_id: resource_id not in owned,
    )
    if not ledger.cleanup():
        raise CleanupError("cleanup_failed")
    comparison = DigestComparison.compare("fake-state", [], [])
    return recorder.build(identity=identity, ledger=ledger, comparisons=[comparison])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("check", "self-test"),
        default="check",
        help="static package check (default) or in-memory fake self-test",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = check_package() if args.command == "check" else fake_self_test()
    except EvidenceCommonError as exc:
        print(json.dumps({"status": "fail", "error": exc.code}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
