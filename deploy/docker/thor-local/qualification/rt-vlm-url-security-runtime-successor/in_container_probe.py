#!/usr/bin/env python3
"""Exercise RT-VLM URL download security controls inside the released image."""

from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import ssl
import sys
from threading import Lock, Thread
from typing import Any

from common.logger import logger
from common.service_exception import ServiceException
from utils import asset_manager


AUTH_HOST = "auth.vss.test"
TARGET_HOST = "target.vss.test"
AUTH_VALUE = "Basic " + base64.b64encode(b"qualification:only").decode()
SMALL_PAYLOAD = b"vss-url-security-small-payload"
LARGE_PAYLOAD = b"L" * 96


class RequestState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._records: list[dict[str, Any]] = []

    def add(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)


class FixtureHandler(BaseHTTPRequestHandler):
    server: "FixtureServer"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self.server.state.add(
            {
                "path": self.path,
                "host": self.headers.get("Host", ""),
                "authorization": self.headers.get("Authorization"),
                "x_forwarded_for": self.headers.get("X-Forwarded-For"),
                "transfer_encoding": self.headers.get("Transfer-Encoding"),
            }
        )
        if self.path == "/redirect-one.mp4":
            self.send_response(302)
            self.send_header("Location", "/small.mp4")
            self.end_headers()
            return
        if self.path == "/redirect-two.mp4":
            self.send_response(302)
            self.send_header("Location", "/redirect-one.mp4")
            self.end_headers()
            return
        if self.path == "/cross-host.mp4":
            self.send_response(302)
            self.send_header(
                "Location",
                f"https://{TARGET_HOST}:{self.server.server_port}/small.mp4",
            )
            self.end_headers()
            return
        if self.path.startswith("/chain-") and self.path.endswith(".mp4"):
            remaining = int(self.path.removeprefix("/chain-").removesuffix(".mp4"))
            if remaining > 0:
                self.send_response(302)
                self.send_header("Location", f"/chain-{remaining - 1}.mp4")
                self.end_headers()
                return
        payload = LARGE_PAYLOAD if self.path == "/large.mp4" else SMALL_PAYLOAD
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: RequestState) -> None:
        self.state = state
        super().__init__(address, FixtureHandler)


class CaptureManager:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    async def save_file(
        self,
        file: Any,
        file_name: str,
        purpose: str,
        media_type: str,
        creation_time: str | None,
        file_id: str,
        url: str,
        sensor_name: str,
    ) -> str:
        payload = await file.read()
        self.saved.append(
            {
                "file_name": file_name,
                "purpose": purpose,
                "media_type": media_type,
                "creation_time": creation_time,
                "file_id": file_id,
                "url": url,
                "sensor_name": sensor_name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        return file_id


@contextmanager
def configured(**values: str | None):
    prior = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def download(url: str, url_headers: dict[str, str] | None = None) -> CaptureManager:
    manager = CaptureManager()
    await asset_manager.AssetManager.download_file(
        manager,
        url=url,
        file_name="fixture.mp4",
        purpose="vision",
        media_type="video",
        creation_time=None,
        file_id="qualification-file",
        url_headers=url_headers,
    )
    return manager


async def expect_service_error(coro: Any, code: str, status: int) -> dict[str, Any]:
    try:
        await coro
    except ServiceException as exc:
        if exc.code != code or exc.status_code != status:
            raise AssertionError(
                f"unexpected service error: {exc.code}/{exc.status_code}, expected {code}/{status}"
            ) from exc
        return {"code": exc.code, "status_code": exc.status_code}
    raise AssertionError(f"expected {code}/{status}")


def auth_flags(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": record["path"],
            "host": record["host"],
            "authorization_present": record["authorization"] is not None,
            "authorization_exact": record["authorization"] == AUTH_VALUE,
            "x_forwarded_for_absent": record["x_forwarded_for"] is None,
            "transfer_encoding_absent": record["transfer_encoding"] is None,
        }
        for record in records
    ]


async def exercise(https_port: int, http_port: int, state: RequestState) -> dict[str, Any]:
    original_validator = asset_manager.validate_url_ssrf_runtime_async
    validator_calls: list[str] = []

    async def bounded_validator(url: str) -> None:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        if host not in {AUTH_HOST, TARGET_HOST}:
            raise AssertionError(f"fixture validator rejected unowned host: {host}")
        validator_calls.append(url)

    asset_manager.validate_url_ssrf_runtime_async = bounded_validator
    original_limit = asset_manager.MAX_DOWNLOAD_FILE_SIZE
    try:
        https_auth = f"https://{AUTH_HOST}:{https_port}"
        https_target = f"https://{TARGET_HOST}:{https_port}"
        http_auth = f"http://{AUTH_HOST}:{http_port}"
        result: dict[str, Any] = {}

        state.reset()
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=None,
            ASSET_DOWNLOAD_MAX_REDIRECTS="0",
            ASSET_DOWNLOAD_AUTH_TOKENS=None,
        ):
            try:
                await download(f"{https_auth}/small.mp4")
            except Exception as exc:  # aiohttp exposes version-specific TLS subclasses
                tls_error_type = type(exc).__name__
            else:
                raise AssertionError("self-signed TLS unexpectedly passed default verification")
        if "Certificate" not in tls_error_type and "SSL" not in tls_error_type:
            raise AssertionError(f"unexpected TLS verification failure: {tls_error_type}")
        result["tls_default"] = {
            "verified": True,
            "self_signed_rejected": True,
            "error_type": tls_error_type,
            "application_requests": len(state.records()),
        }

        state.reset()
        with configured(ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST):
            manager = await download(f"{https_auth}/small.mp4")
        result["tls_listed_domain"] = {
            "skip_config": [AUTH_HOST],
            "downloaded": len(manager.saved) == 1,
            "bytes": manager.saved[0]["bytes"],
            "payload_sha256": manager.saved[0]["sha256"],
        }

        state.reset()
        with configured(ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST):
            try:
                await download(f"{https_target}/small.mp4")
            except Exception as exc:
                unlisted_error_type = type(exc).__name__
            else:
                raise AssertionError("unlisted self-signed TLS domain unexpectedly passed")
        if "Certificate" not in unlisted_error_type and "SSL" not in unlisted_error_type:
            raise AssertionError(f"unexpected unlisted TLS failure: {unlisted_error_type}")
        result["tls_unlisted_domain"] = {
            "verification_retained": True,
            "self_signed_rejected": True,
            "error_type": unlisted_error_type,
        }

        state.reset()
        with configured(ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST):
            await download(
                f"{https_auth}/auth.mp4",
                {
                    "Authorization": AUTH_VALUE,
                    "Host": "blocked.invalid",
                    "X-Forwarded-For": "192.0.2.1",
                    "Transfer-Encoding": "chunked",
                },
            )
        request_auth = auth_flags(state.records())
        if len(request_auth) != 1 or not request_auth[0]["authorization_exact"]:
            raise AssertionError("request-level Authorization header was not delivered")
        if not request_auth[0]["x_forwarded_for_absent"] or not request_auth[0]["transfer_encoding_absent"]:
            raise AssertionError("a disallowed request header escaped the allowlist")
        if request_auth[0]["host"].startswith("blocked.invalid"):
            raise AssertionError("Host override escaped the allowlist")
        result["request_headers"] = {
            "request_count": 1,
            "authorization_delivered": True,
            "disallowed_host_blocked": True,
            "disallowed_forwarded_for_blocked": True,
            "disallowed_transfer_encoding_blocked": True,
        }

        state.reset()
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST,
            ASSET_DOWNLOAD_AUTH_TOKENS=f"{AUTH_HOST}={AUTH_VALUE}",
        ):
            await download(f"{https_auth}/auth.mp4")
        env_auth = auth_flags(state.records())
        if len(env_auth) != 1 or not env_auth[0]["authorization_exact"]:
            raise AssertionError("domain-scoped environment Authorization was not delivered")
        result["environment_auth"] = {
            "matched_domain": AUTH_HOST,
            "authorization_delivered": True,
            "unmatched_domain_authorization_stripped": False,
        }

        state.reset()
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=TARGET_HOST,
            ASSET_DOWNLOAD_AUTH_TOKENS=f"{AUTH_HOST}={AUTH_VALUE}",
        ):
            await download(f"{https_target}/auth.mp4")
        env_unmatched = auth_flags(state.records())
        if len(env_unmatched) != 1 or env_unmatched[0]["authorization_present"]:
            raise AssertionError("domain-scoped environment Authorization leaked to unmatched host")
        result["environment_auth"]["unmatched_domain_authorization_stripped"] = True

        state.reset()
        with configured(ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=None):
            await download(
                f"{http_auth}/auth.mp4",
                {"Authorization": AUTH_VALUE},
            )
        plain_http = auth_flags(state.records())
        if len(plain_http) != 1 or plain_http[0]["authorization_present"]:
            raise AssertionError("Authorization leaked over plain HTTP")
        result["plain_http"] = {"authorization_stripped": True, "downloaded": True}

        state.reset()
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=f"{AUTH_HOST},{TARGET_HOST}",
            ASSET_DOWNLOAD_MAX_REDIRECTS="1",
        ):
            await download(
                f"{https_auth}/cross-host.mp4",
                {"Authorization": AUTH_VALUE},
            )
        cross = auth_flags(state.records())
        if len(cross) != 2 or not cross[0]["authorization_exact"] or cross[1]["authorization_present"]:
            raise AssertionError("cross-host redirect Authorization boundary drifted")
        result["cross_host_redirect"] = {
            "source_authorization_delivered": True,
            "target_authorization_stripped": True,
            "target_host": TARGET_HOST,
        }

        state.reset()
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST,
            ASSET_DOWNLOAD_MAX_REDIRECTS="1",
        ):
            await download(
                f"{https_auth}/redirect-one.mp4",
                {"Authorization": AUTH_VALUE},
            )
        same = auth_flags(state.records())
        if len(same) != 2 or not all(record["authorization_exact"] for record in same):
            raise AssertionError("same-host redirect did not retain Authorization")
        result["same_host_redirect"] = {
            "hops": 1,
            "authorization_retained": True,
        }

        state.reset()
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST,
            ASSET_DOWNLOAD_MAX_REDIRECTS="0",
        ):
            redirect_zero = await expect_service_error(
                download(f"{https_auth}/redirect-one.mp4"), "RedirectNotAllowed", 422
            )
        result["redirect_limit_zero"] = {
            **redirect_zero,
            "request_paths": [record["path"] for record in state.records()],
        }

        state.reset()
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST,
            ASSET_DOWNLOAD_MAX_REDIRECTS="1",
        ):
            redirect_one = await expect_service_error(
                download(f"{https_auth}/redirect-two.mp4"), "RedirectNotAllowed", 422
            )
        result["redirect_limit_one"] = {
            **redirect_one,
            "request_paths": [record["path"] for record in state.records()],
        }

        state.reset()
        validator_before = len(validator_calls)
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST,
            ASSET_DOWNLOAD_MAX_REDIRECTS="2",
        ):
            manager = await download(f"{https_auth}/redirect-two.mp4")
        result["redirect_limit_two"] = {
            "downloaded": len(manager.saved) == 1,
            "request_paths": [record["path"] for record in state.records()],
            "ssrf_validation_calls": len(validator_calls) - validator_before,
        }

        state.reset()
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST,
            ASSET_DOWNLOAD_MAX_REDIRECTS="-1",
        ):
            redirect_negative = await expect_service_error(
                download(f"{https_auth}/redirect-one.mp4"), "RedirectNotAllowed", 422
            )
        result["redirect_negative_clamped"] = {
            **redirect_negative,
            "effective_limit": 0,
            "request_count": len(state.records()),
        }

        state.reset()
        with configured(
            ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST,
            ASSET_DOWNLOAD_MAX_REDIRECTS="20",
        ):
            redirect_above_max = await expect_service_error(
                download(f"{https_auth}/chain-11.mp4"), "RedirectNotAllowed", 422
            )
        chain_paths = [record["path"] for record in state.records()]
        if len(chain_paths) != 11 or chain_paths[-1] != "/chain-1.mp4":
            raise AssertionError(f"redirect maximum did not clamp at ten hops: {chain_paths}")
        result["redirect_above_max_clamped"] = {
            **redirect_above_max,
            "configured_limit": 20,
            "effective_limit": 10,
            "request_count": len(chain_paths),
            "terminal_request_path": chain_paths[-1],
        }

        with configured(ASSET_DOWNLOAD_MAX_FILE_SIZE_GB=None):
            default_limit = asset_manager._parse_max_download_file_size_bytes()
        sixty_four_gib_fraction = str(64 / (1024**3))
        with configured(ASSET_DOWNLOAD_MAX_FILE_SIZE_GB=sixty_four_gib_fraction):
            configured_limit = asset_manager._parse_max_download_file_size_bytes()
        if configured_limit != 64:
            raise AssertionError(f"fractional size config did not produce 64 bytes: {configured_limit}")
        asset_manager.MAX_DOWNLOAD_FILE_SIZE = configured_limit
        state.reset()
        with configured(ASSET_DOWNLOAD_SSL_SKIP_VERIFY_DOMAINS=AUTH_HOST):
            small_manager = await download(f"{https_auth}/small.mp4")
            saved_before_large = len(small_manager.saved)
            large_error = await expect_service_error(
                asset_manager.AssetManager.download_file(
                    small_manager,
                    url=f"{https_auth}/large.mp4",
                    file_name="fixture.mp4",
                    purpose="vision",
                    media_type="video",
                    creation_time=None,
                    file_id="qualification-large",
                    url_headers=None,
                ),
                "FileTooLarge",
                413,
            )
        result["download_size"] = {
            "default_limit_bytes": default_limit,
            "configured_limit_bytes": configured_limit,
            "at_or_below_limit_saved": saved_before_large == 1,
            "below_limit_bytes": small_manager.saved[0]["bytes"],
            "over_limit_response_bytes": len(LARGE_PAYLOAD),
            "over_limit_not_saved": len(small_manager.saved) == saved_before_large,
            **large_error,
        }

        result["fixture"] = {
            "https_port": https_port,
            "http_port": http_port,
            "owned_hosts": [AUTH_HOST, TARGET_HOST],
            "ssrf_guard_bypass": "bounded_fixture_hosts_only",
            "validator_calls": len(validator_calls),
            "small_payload_sha256": hashlib.sha256(SMALL_PAYLOAD).hexdigest(),
        }
        return result
    finally:
        asset_manager.validate_url_ssrf_runtime_async = original_validator
        asset_manager.MAX_DOWNLOAD_FILE_SIZE = original_limit


def start_server(state: RequestState, tls: bool, cert: Path, key: Path) -> FixtureServer:
    server = FixtureServer(("0.0.0.0", 0), state)
    if tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: in_container_probe.py CERT KEY")
    logger.setLevel(logging.CRITICAL)
    state = RequestState()
    cert, key = Path(sys.argv[1]), Path(sys.argv[2])
    https_server = start_server(state, True, cert, key)
    http_server = start_server(state, False, cert, key)
    try:
        result = asyncio.run(
            exercise(https_server.server_port, http_server.server_port, state)
        )
        print("QUALIFICATION_JSON=" + json.dumps(result, sort_keys=True))
        return 0
    finally:
        https_server.shutdown()
        http_server.shutdown()
        https_server.server_close()
        http_server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
