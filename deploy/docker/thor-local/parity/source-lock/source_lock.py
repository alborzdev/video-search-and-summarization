#!/usr/bin/env python3

"""Capture and validate byte hashes for the official VSS documentation source set."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


SCRIPT_DIR = Path(__file__).resolve().parent
PARITY_DIR = SCRIPT_DIR.parent
REPO_ROOT = SCRIPT_DIR.parents[4]
LOCK = SCRIPT_DIR / "source-lock.json"
SCHEMA = SCRIPT_DIR / "source-lock.schema.json"
INPUTS = {
    "live_ledger": PARITY_DIR / "official-capabilities.json",
    "wave2_candidate": PARITY_DIR / "candidates/wave2/candidate.json",
    "recursive_targets": (
        PARITY_DIR
        / "candidates/wave3/recursive-coverage/recursive-targets.json"
    ),
}
DOC_SOURCE_KINDS = {"versioned_official_docs", "release_notes"}
PRODUCT_VERSION = "3.2.1"
SCHEMA_VERSION = 3
CAPTURE_DATE = "2026-07-31"
RECURSIVE_TARGET_COUNT = 172
RECURSIVE_TARGET_SET_SHA256 = (
    "74a1d6ae1f520049202e47dce69fa56d10c28c48aa3aa24a3a2c4214dad4b208"
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ALLOWED_CONTENT_TYPE = re.compile(
    r"^(?:text/html|application/xhtml\+xml)(?:\s*;|$)", re.IGNORECASE
)
FETCH_OPTIONS = [
    "--silent",
    "--show-error",
    "--request",
    "GET",
    "--proto",
    "=https",
    "--connect-timeout",
    "20",
    "--max-time",
    "90",
    "--retry",
    "2",
    "--retry-delay",
    "1",
    "--retry-all-errors",
    "--header",
    "Accept: text/html, application/xhtml+xml",
    "--header",
    "Accept-Encoding: identity",
    "--header",
    "Accept-Language: en-US",
    "--user-agent",
    "VSS-Thor-source-lock/1.0",
]
CURL_PATH = "/usr/bin/curl"
CURL_VERSION = (
    "curl 8.5.0 (aarch64-unknown-linux-gnu) libcurl/8.5.0 OpenSSL/3.0.13 "
    "zlib/1.3 brotli/1.1.0 zstd/1.5.5 libidn2/2.3.7 libpsl/0.21.2 "
    "(+libidn2/2.3.7) libssh/0.10.6/openssl/zlib nghttp2/1.59.0 librtmp/2.3 "
    "OpenLDAP/2.6.7"
)
SANITIZED_ENV = {
    "LANG": "C",
    "LC_ALL": "C",
    "NO_PROXY": "*",
    "no_proxy": "*",
    "PATH": "/usr/bin:/bin",
}
EXPECTED_INTERPRETATION = {
    "source_kind": "mutable_versioned_web_document",
    "hash_scope": "raw_response_body_bytes_only",
    "semantic_extraction_proof": False,
}


@dataclass(frozen=True)
class CurlResponse:
    """One non-following curl response, including response-header metadata."""

    status: int | None
    content_type: str | None
    content_encoding: str | None
    body: bytes
    effective_url: str | None
    location: str | None
    error: str | None


class SourceLockError(ValueError):
    """The source lock is malformed, stale, or unsafe."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SourceLockError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_pairs
    )
    if not isinstance(value, dict):
        raise SourceLockError(f"{path.name}: root must be an object")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(canonical)


def validate_capture_date(value: str) -> None:
    if not isinstance(value, str) or DATE.fullmatch(value) is None:
        raise SourceLockError("captured_on must be an explicit YYYY-MM-DD date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise SourceLockError("captured_on is not a calendar date") from exc
    if parsed.isoformat() != value:
        raise SourceLockError("captured_on must use canonical YYYY-MM-DD form")


def fetch_policy() -> dict[str, Any]:
    return {
        "tool": {
            "name": "curl",
            "path": CURL_PATH,
            "version": CURL_VERSION,
        },
        "options": ["--disable", *FETCH_OPTIONS],
        "environment": {
            "mode": "process_environment_replaced",
            "variables": SANITIZED_ENV,
            "proxy_mode": "direct_no_proxy",
            "curl_config_mode": "disabled",
        },
        "trust": {
            "mode": "curl_compiled_default_system_ca_store",
            "custom_ca_environment": False,
            "certificate_verification_disabled": False,
        },
        "redirect_mode": "manual_same_host_https_version_path_only",
        "max_redirects": 5,
        "accepted_content_types": ["text/html", "application/xhtml+xml"],
        "requested_content_encoding": "identity",
        "accepted_content_encoding": "identity",
        "store_response_bodies": False,
    }


def verify_curl_identity() -> None:
    completed = subprocess.run(
        [CURL_PATH, "--disable", "--version"],
        capture_output=True,
        text=True,
        check=False,
        env=SANITIZED_ENV,
    )
    first_line = completed.stdout.splitlines()[0] if completed.stdout else ""
    if completed.returncode != 0 or first_line != CURL_VERSION:
        raise SourceLockError(
            "curl path/version differs from the reviewed fetch policy: "
            f"expected {CURL_PATH} {CURL_VERSION!r}, observed {first_line!r}"
        )


def _validate_docs_url(url: str, *, require_versioned_path: bool) -> None:
    if not isinstance(url, str):
        raise SourceLockError("documentation URL must be a string")
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as exc:
        raise SourceLockError(f"unsafe documentation URL: {url!r}") from exc
    if (
        parts.scheme != "https"
        or parts.hostname != "docs.nvidia.com"
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.query
        or parts.fragment
    ):
        raise SourceLockError(f"unsafe documentation URL: {url!r}")
    if require_versioned_path and not parts.path.startswith("/vss/3.2.1/"):
        raise SourceLockError(f"URL is outside the VSS 3.2.1 path: {url!r}")


def resolve_redirect(current_url: str, location: str) -> str:
    if not location or "\r" in location or "\n" in location:
        raise SourceLockError("redirect Location is missing or malformed")
    target = urljoin(current_url, location)
    _validate_docs_url(target, require_versioned_path=True)
    return target


def source_urls(
    inputs: dict[str, Path] = INPUTS,
) -> dict[str, list[str]]:
    """Return the exact recursive allowlist with semantic-source provenance."""
    if set(inputs) != {"live_ledger", "wave2_candidate", "recursive_targets"}:
        raise SourceLockError("source inputs must be the reviewed three-input set")
    target_document = load_json(inputs["recursive_targets"])
    targets = target_document.get("targets")
    if (
        not isinstance(targets, list)
        or targets != sorted(targets)
        or len(targets) != RECURSIVE_TARGET_COUNT
        or len(set(targets)) != RECURSIVE_TARGET_COUNT
        or target_document.get("reachable_count_including_start")
        != RECURSIVE_TARGET_COUNT
        or target_document.get("canonical_reachable_set_sha256")
        != RECURSIVE_TARGET_SET_SHA256
        or canonical_json_hash(targets) != RECURSIVE_TARGET_SET_SHA256
    ):
        raise SourceLockError("recursive target allowlist is not the reviewed 172-URL set")
    result: dict[str, list[str]] = {}
    for url in targets:
        _validate_docs_url(url, require_versioned_path=True)
        if not url.endswith(".html"):
            raise SourceLockError(f"recursive target is not an HTML page: {url!r}")
        result[url] = ["recursive_fixed_point"]

    for label in ("live_ledger", "wave2_candidate"):
        path = inputs[label]
        document = load_json(path)
        sources = document.get("sources")
        if not isinstance(sources, list):
            raise SourceLockError(f"{label}: sources must be a list")
        for source in sources:
            if not isinstance(source, dict):
                raise SourceLockError(f"{label}: source must be an object")
            if source.get("kind") not in DOC_SOURCE_KINDS:
                continue
            url = source.get("uri")
            _validate_docs_url(url, require_versioned_path=True)
            if url not in result:
                raise SourceLockError(
                    f"{label}: documentation source is outside recursive allowlist: {url}"
                )
            result[url].append(label)
    return {url: sorted(set(labels)) for url, labels in sorted(result.items())}


def canonical_record_hash(records: list[dict[str, Any]]) -> str:
    return canonical_json_hash(sorted(records, key=lambda item: item["url"]))


def _final_header_block(header_bytes: bytes) -> bytes:
    normalized = header_bytes.replace(b"\r\n", b"\n")
    blocks = [
        block for block in normalized.split(b"\n\n") if block.startswith(b"HTTP/")
    ]
    return blocks[-1] if blocks else b""


def _header_values(header_bytes: bytes, name: str) -> list[str]:
    target = name.lower().encode("ascii") + b":"
    values: list[str] = []
    for line in _final_header_block(header_bytes).splitlines():
        if line.lower().startswith(target):
            values.append(line.split(b":", 1)[1].strip().decode("latin-1"))
    return values


def _curl_once(url: str, work: Path) -> CurlResponse:
    headers = work / "headers"
    body = work / "body"
    headers.write_bytes(b"")
    body.write_bytes(b"")
    command = [
        CURL_PATH,
        "--disable",
        *FETCH_OPTIONS,
        "--dump-header",
        str(headers),
        "--output",
        str(body),
        "--write-out",
        "%{http_code}\\n%{content_type}\\n%{url_effective}",
        url,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=SANITIZED_ENV,
    )
    output = completed.stdout.splitlines()
    status = int(output[0]) if output and output[0].isdigit() else None
    content_type = output[1].strip() if len(output) > 1 and output[1].strip() else None
    effective = output[2].strip() if len(output) > 2 and output[2].strip() else None
    response = body.read_bytes() if body.exists() else b""
    header_bytes = headers.read_bytes() if headers.exists() else b""
    locations = _header_values(header_bytes, "location")
    encodings = _header_values(header_bytes, "content-encoding")
    location = locations[0] if len(locations) == 1 else None
    content_encoding = "identity" if not encodings else ",".join(encodings).lower()
    error = None
    if completed.returncode != 0:
        error = completed.stderr.strip() or f"curl exited {completed.returncode}"
    elif effective != url:
        error = "curl changed URL without manual redirect"
    elif len(locations) > 1:
        error = "response contained multiple Location headers"
    elif len(encodings) > 1:
        error = "response contained multiple Content-Encoding headers"
    return CurlResponse(
        status=status,
        content_type=content_type,
        content_encoding=content_encoding,
        body=response,
        effective_url=effective,
        location=location,
        error=error,
    )


def fetch_url(
    url: str, referenced_by: list[str], *, max_redirects: int = 5
) -> dict[str, Any]:
    _validate_docs_url(url, require_versioned_path=True)
    current = url
    status: int | None = None
    content_type: str | None = None
    content_encoding: str | None = None
    body = b""
    failure: str | None = None
    visited = {url}
    with tempfile.TemporaryDirectory(prefix="vss-doc-lock-") as temp:
        work = Path(temp)
        for redirect_count in range(max_redirects + 1):
            response = _curl_once(current, work)
            status = response.status
            content_type = response.content_type
            content_encoding = response.content_encoding
            body = response.body
            if response.error:
                failure = response.error
                break
            if status is None:
                failure = "curl did not return an HTTP status"
                break
            if 300 <= status < 400:
                if redirect_count == max_redirects:
                    failure = f"redirect limit exceeded ({max_redirects})"
                    break
                try:
                    target = resolve_redirect(current, response.location or "")
                except SourceLockError as exc:
                    failure = str(exc)
                    break
                if target in visited:
                    failure = "redirect loop detected"
                    break
                visited.add(target)
                current = target
                continue
            if status != 200:
                failure = f"unexpected HTTP status {status}"
            elif (
                content_type is None or ALLOWED_CONTENT_TYPE.match(content_type) is None
            ):
                failure = f"unexpected content type {content_type!r}"
            elif content_encoding != "identity":
                failure = f"unexpected content encoding {content_encoding!r}"
            elif not body:
                failure = "empty response body"
            break
    success = failure is None
    return {
        "url": url,
        "referenced_by": referenced_by,
        "outcome": "success" if success else "failure",
        "final_url": current,
        "http_status": status,
        "content_type": content_type,
        "content_encoding": content_encoding,
        "byte_count": len(body) if success else None,
        "sha256": sha256_bytes(body) if success else None,
        "failure": failure,
    }


def build_lock(captured_on: str, inputs: dict[str, Path] = INPUTS) -> dict[str, Any]:
    validate_capture_date(captured_on)
    if captured_on != CAPTURE_DATE:
        raise SourceLockError(
            f"this source-lock snapshot requires captured_on {CAPTURE_DATE}"
        )
    verify_curl_identity()
    urls = source_urls(inputs)
    records = [fetch_url(url, labels) for url, labels in urls.items()]
    final_urls = [item["final_url"] for item in records]
    if len(final_urls) != len(set(final_urls)):
        raise SourceLockError("fetch produced duplicate or colliding final URLs")
    success_count = sum(item["outcome"] == "success" for item in records)
    return {
        "schema_version": SCHEMA_VERSION,
        "product_version": PRODUCT_VERSION,
        "captured_on": captured_on,
        "inputs": [
            {
                "id": label,
                "path": str(path.relative_to(REPO_ROOT)),
                "sha256": sha256_file(path),
            }
            for label, path in inputs.items()
        ],
        "fetch_policy": fetch_policy(),
        "interpretation": EXPECTED_INTERPRETATION,
        "records": records,
        "summary": {
            "url_count": len(records),
            "success_count": success_count,
            "failure_count": len(records) - success_count,
            "total_byte_count": sum(
                item["byte_count"] or 0 for item in records
            ),
            "aggregate_sha256": canonical_record_hash(records),
        },
    }


def _schema_validate(document: dict[str, Any]) -> None:
    schema = load_json(SCHEMA)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SourceLockError(f"invalid source lock schema: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            document
        ),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise SourceLockError(f"schema violation at {location}: {error.message}")


def validate(
    document: dict[str, Any] | None = None,
    *,
    inputs: dict[str, Path] = INPUTS,
) -> dict[str, Any]:
    document = load_json(LOCK) if document is None else document
    _schema_validate(document)
    if document["product_version"] != PRODUCT_VERSION:
        raise SourceLockError("product version changed")
    validate_capture_date(document["captured_on"])
    if document["captured_on"] != CAPTURE_DATE:
        raise SourceLockError("capture date differs from the reviewed snapshot")
    if document["interpretation"] != EXPECTED_INTERPRETATION:
        raise SourceLockError("source hash interpretation is not fail-closed")
    if document["fetch_policy"] != fetch_policy():
        raise SourceLockError("fetch policy differs from the reviewed capture policy")

    expected_inputs = [
        {
            "id": label,
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(path),
        }
        for label, path in inputs.items()
    ]
    if document["inputs"] != expected_inputs:
        raise SourceLockError(
            "input path or byte hash differs from the captured source set"
        )

    expected_urls = source_urls(inputs)
    records = document["records"]
    urls = [item["url"] for item in records]
    if urls != sorted(urls) or len(urls) != len(set(urls)):
        raise SourceLockError("records must have unique URLs in lexical order")
    if set(urls) != set(expected_urls):
        raise SourceLockError(
            "locked URLs differ from the exact recursive target allowlist"
        )
    final_urls = [item["final_url"] for item in records]
    if len(final_urls) != len(set(final_urls)):
        raise SourceLockError("records contain duplicate or colliding final URLs")
    for record in records:
        url = record["url"]
        _validate_docs_url(url, require_versioned_path=True)
        _validate_docs_url(record["final_url"], require_versioned_path=True)
        if record["referenced_by"] != expected_urls[url]:
            raise SourceLockError(
                f"{url}: captured source references differ from exact provenance"
            )
        if record["outcome"] == "success":
            if record["http_status"] != 200:
                raise SourceLockError(f"{url}: successful record must have HTTP 200")
            if ALLOWED_CONTENT_TYPE.match(record["content_type"]) is None:
                raise SourceLockError(f"{url}: unexpected content type")
            if record["content_encoding"] != "identity":
                raise SourceLockError(f"{url}: unexpected content encoding")
            if record["byte_count"] <= 0 or HEX64.fullmatch(record["sha256"]) is None:
                raise SourceLockError(f"{url}: successful body metadata is incomplete")
        elif not record["failure"]:
            raise SourceLockError(f"{url}: failed record must explain the failure")

    success_count = sum(item["outcome"] == "success" for item in records)
    expected_summary = {
        "url_count": len(records),
        "success_count": success_count,
        "failure_count": len(records) - success_count,
        "total_byte_count": sum(item["byte_count"] or 0 for item in records),
        "aggregate_sha256": canonical_record_hash(records),
    }
    if document["summary"] != expected_summary:
        raise SourceLockError("summary counts or aggregate hash differ")
    return expected_summary


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    """Atomically install JSON without allowing a capture-date relabel in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SourceLockError("output path must not be a symlink")
    if path.exists():
        existing = load_json(path)
        if existing.get("captured_on") != document["captured_on"]:
            raise SourceLockError(
                "refusing to relabel an existing snapshot; choose a new --output path"
            )
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("fetch", "validate"), nargs="?", default="validate"
    )
    parser.add_argument("--output", type=Path, default=LOCK)
    parser.add_argument(
        "--captured-on",
        help="explicit YYYY-MM-DD snapshot date; required for fetch",
    )
    args = parser.parse_args()
    try:
        if args.command == "fetch":
            if args.captured_on is None:
                raise SourceLockError(
                    "fetch requires explicit --captured-on YYYY-MM-DD"
                )
            document = build_lock(args.captured_on)
            summary = validate(document)
            atomic_write_json(args.output, document)
        else:
            if args.captured_on is not None:
                raise SourceLockError("--captured-on is valid only with fetch")
            summary = validate()
    except (OSError, SourceLockError, subprocess.SubprocessError) as exc:
        print(f"source lock: FAIL: {exc}", file=sys.stderr)
        return 1
    if summary["failure_count"]:
        print(
            "source lock: INCOMPLETE: "
            f"{summary['url_count']} URLs, {summary['success_count']} success, "
            f"{summary['failure_count']} failure, "
            f"{summary['total_byte_count']} bytes, "
            f"aggregate={summary['aggregate_sha256']}",
            file=sys.stderr,
        )
        return 1
    print(
        "source lock: PASS: "
        f"{summary['url_count']} URLs, {summary['success_count']} success, "
        f"{summary['failure_count']} failure, "
        f"{summary['total_byte_count']} bytes, "
        f"aggregate={summary['aggregate_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
