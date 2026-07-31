# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QUALIFICATION_DIR))

import runtime  # noqa: E402


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self.server.request_methods.append("GET")  # type: ignore[attr-defined]
        route = self.server.routes.get(self.path)  # type: ignore[attr-defined]
        if route is None:
            status, headers, body = 404, {}, b"not found"
        else:
            status, headers, body = route
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        self.server.request_methods.append("POST")  # type: ignore[attr-defined]
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


@contextmanager
def mock_http_server(
    routes: dict[str, tuple[int, dict[str, str], bytes]],
) -> Iterator[tuple[str, ThreadingHTTPServer]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    server.routes = routes  # type: ignore[attr-defined]
    server.request_methods = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def openapi_document(*paths: str) -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": "mock", "version": "1"},
        "paths": {
            path: {
                "get": {
                    "operationId": "get_" + path.strip("/").replace("/", "_"),
                    "responses": {"200": {"description": "ok"}},
                }
            }
            for path in paths
        },
    }


def expected_manifest(document: dict[str, Any]) -> dict[str, Any]:
    operations, component_hash = runtime.normalize_openapi_document(document)
    return {
        "component_schema_hash": component_hash,
        "kind": "rest",
        "operations": operations,
        "surface": "mock",
    }


def write_fixture(
    root: Path,
    probes: list[dict[str, Any]],
    *,
    manifest: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    config = {
        "schema_version": 1,
        "services": [
            {
                "id": "mock",
                "default_port": 1,
                "probes": probes,
            }
        ],
    }
    config_path = root / "runtime.json"
    expected_dir = root / "expected"
    expected_dir.mkdir()
    config_path.write_text(json.dumps(config), encoding="utf-8")
    if manifest is not None:
        (expected_dir / "mock.json").write_text(json.dumps(manifest), encoding="utf-8")
    return config_path, expected_dir


class RuntimeQualificationTests(unittest.TestCase):
    def test_versioned_inventory_is_loopback_get_only(self) -> None:
        config = runtime.load_runtime_config(runtime.DEFAULT_CONFIG)
        services = config["services"]
        probes = [probe for service in services for probe in service["probes"]]

        self.assertEqual(len(services), 13)
        self.assertEqual(len(probes), 20)
        self.assertNotIn("local-llm", {service["id"] for service in services})
        self.assertNotIn("local-vlm", {service["id"] for service in services})
        self.assertTrue(all(probe.get("method", "GET") == "GET" for probe in probes))

    def test_health_openapi_and_mcp_probes_pass_with_get_only(self) -> None:
        document = openapi_document("/widgets")
        body = json.dumps(document).encode()
        routes = {
            "/health": (200, {"Content-Type": "application/json"}, b"{}"),
            "/openapi.json": (200, {"Content-Type": "application/json"}, body),
            "/sse": (200, {"Content-Type": "text/event-stream"}, b""),
        }
        probes = [
            {"id": "health", "kind": "health", "path": "/health"},
            {
                "id": "openapi",
                "kind": "openapi",
                "path": "/openapi.json",
                "expected_manifest": "mock.json",
            },
            {
                "id": "mcp",
                "kind": "mcp",
                "mode": "sse",
                "path": "/sse",
            },
        ]
        with (
            tempfile.TemporaryDirectory() as temp,
            mock_http_server(routes) as (
                origin,
                server,
            ),
        ):
            config, expected = write_fixture(
                Path(temp), probes, manifest=expected_manifest(document)
            )
            report = runtime.run_runtime(
                config,
                expected,
                endpoint_assignments=[f"mock={origin}"],
                timeout=1,
            )

        self.assertEqual(report["result"], "pass")
        self.assertEqual(
            report["summary"],
            {
                "failed": 0,
                "passed": 3,
                "skipped": 0,
                "total": 3,
                "unavailable": 0,
            },
        )
        self.assertEqual(server.request_methods, ["GET", "GET", "GET"])  # type: ignore[attr-defined]
        openapi_result = next(
            item for item in report["probes"] if item["kind"] == "openapi"
        )
        self.assertEqual(openapi_result["comparison"]["missing_route_count"], 0)
        self.assertEqual(openapi_result["comparison"]["extra_route_count"], 0)

    def test_optional_openapi_404_is_skipped(self) -> None:
        probes = [
            {
                "id": "openapi",
                "kind": "openapi",
                "path": "/openapi.json",
                "availability": "optional",
                "expected_manifest": "mock.json",
            }
        ]
        routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
        with (
            tempfile.TemporaryDirectory() as temp,
            mock_http_server(routes) as (
                origin,
                _,
            ),
        ):
            config, expected = write_fixture(
                Path(temp), probes, manifest=expected_manifest(openapi_document("/ok"))
            )
            report = runtime.run_runtime(
                config,
                expected,
                endpoint_assignments=[f"mock={origin}"],
                timeout=1,
            )
        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["summary"]["skipped"], 1)
        self.assertEqual(report["probes"][0]["error"], "not_available")

    def test_stopped_service_is_unavailable_not_failed_or_skipped(self) -> None:
        probes = [{"id": "health", "kind": "health", "path": "/health"}]
        server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        origin = f"http://127.0.0.1:{server.server_port}"
        server.server_close()
        with tempfile.TemporaryDirectory() as temp:
            config, expected = write_fixture(Path(temp), probes)
            report = runtime.run_runtime(
                config,
                expected,
                endpoint_assignments=[f"mock={origin}"],
                timeout=0.2,
            )
        self.assertEqual(report["result"], "unavailable")
        self.assertEqual(report["summary"]["unavailable"], 1)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["skipped"], 0)
        self.assertEqual(report["probes"][0]["status"], "unavailable")
        self.assertEqual(report["probes"][0]["error"], "connection_refused")

    def test_contract_drift_reports_counts_and_hash_not_live_paths(self) -> None:
        secret = "Bearer-super-secret"
        expected_doc = openapi_document("/widgets")
        live_doc = openapi_document("/widgets", f"/{secret}")
        routes = {
            "/openapi.json": (
                200,
                {"Content-Type": "application/json"},
                json.dumps(live_doc).encode(),
            )
        }
        probes = [
            {
                "id": "openapi",
                "kind": "openapi",
                "path": "/openapi.json",
                "expected_manifest": "mock.json",
            }
        ]
        with (
            tempfile.TemporaryDirectory() as temp,
            mock_http_server(routes) as (
                origin,
                _,
            ),
        ):
            config, expected = write_fixture(
                Path(temp), probes, manifest=expected_manifest(expected_doc)
            )
            report = runtime.run_runtime(
                config,
                expected,
                endpoint_assignments=[f"mock={origin}"],
                timeout=1,
            )
        serialized = json.dumps(report)
        self.assertEqual(report["result"], "fail")
        self.assertEqual(report["probes"][0]["error"], "contract_drift")
        self.assertEqual(report["probes"][0]["comparison"]["extra_route_count"], 1)
        self.assertIn("drift_fingerprint", report["probes"][0]["comparison"])
        self.assertNotIn(secret, serialized)

    def test_http_error_body_and_redirect_location_are_redacted(self) -> None:
        secret = "do-not-print-this-token"
        routes = {
            "/error": (500, {"Content-Type": "text/plain"}, secret.encode()),
            "/redirect": (
                302,
                {"Location": f"http://example.invalid/{secret}"},
                b"",
            ),
        }
        probes = [
            {"id": "error", "kind": "health", "path": "/error"},
            {"id": "redirect", "kind": "health", "path": "/redirect"},
        ]
        with (
            tempfile.TemporaryDirectory() as temp,
            mock_http_server(routes) as (
                origin,
                _,
            ),
        ):
            config, expected = write_fixture(Path(temp), probes)
            report = runtime.run_runtime(
                config,
                expected,
                endpoint_assignments=[f"mock={origin}"],
                timeout=1,
            )
        errors = {item["id"]: item["error"] for item in report["probes"]}
        self.assertEqual(errors["mock:error"], "http_error")
        self.assertEqual(errors["mock:redirect"], "redirect_refused")
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("example.invalid", json.dumps(report))

    def test_allowlisted_redirect_is_reachability_without_following_it(self) -> None:
        secret = "redirect-target-must-stay-redacted"
        routes = {
            "/": (
                307,
                {"Location": f"http://example.invalid/{secret}"},
                b"",
            )
        }
        probes = [
            {
                "id": "root",
                "kind": "reachability",
                "path": "/",
                "expected_status": [200, 307],
            }
        ]
        with (
            tempfile.TemporaryDirectory() as temp,
            mock_http_server(routes) as (
                origin,
                server,
            ),
        ):
            config, expected = write_fixture(Path(temp), probes)
            report = runtime.run_runtime(
                config,
                expected,
                endpoint_assignments=[f"mock={origin}"],
                timeout=1,
            )
        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["probes"][0]["http_status"], 307)
        self.assertEqual(server.request_methods, ["GET"])  # type: ignore[attr-defined]
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("example.invalid", json.dumps(report))

    def test_non_loopback_override_and_non_get_config_are_rejected(self) -> None:
        health = [{"id": "health", "kind": "health", "path": "/health"}]
        with tempfile.TemporaryDirectory() as temp:
            config, expected = write_fixture(Path(temp), health)
            external = runtime.run_runtime(
                config,
                expected,
                endpoint_assignments=["mock=http://example.com:80"],
            )
            self.assertEqual(external["probes"][0]["error"], "configuration_error")

            bad_config = json.loads(config.read_text(encoding="utf-8"))
            bad_config["services"][0]["probes"][0]["method"] = "POST"
            config.write_text(json.dumps(bad_config), encoding="utf-8")
            non_get = runtime.run_runtime(config, expected)
            self.assertEqual(non_get["probes"][0]["error"], "configuration_error")

    def test_cli_always_emits_json(self) -> None:
        routes = {"/health": (200, {}, b"")}
        probes = [{"id": "health", "kind": "health", "path": "/health"}]
        with (
            tempfile.TemporaryDirectory() as temp,
            mock_http_server(routes) as (
                origin,
                _,
            ),
        ):
            config, expected = write_fixture(Path(temp), probes)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = runtime.main(
                    [
                        "--config",
                        str(config),
                        "--expected-dir",
                        str(expected),
                        "--endpoint",
                        f"mock={origin}",
                        "--compact",
                    ]
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["result"], "pass")

    def test_runtime_module_has_no_process_or_container_control(self) -> None:
        source = (QUALIFICATION_DIR / "runtime.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots: set[str] = set()
        called_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_names.add(node.func.attr)
        self.assertFalse({"docker", "subprocess"} & imported_roots)
        self.assertFalse(
            {"Popen", "run", "system", "write_text", "unlink"} & called_names
        )


if __name__ == "__main__":
    unittest.main()
