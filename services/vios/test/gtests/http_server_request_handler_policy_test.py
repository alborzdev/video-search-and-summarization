# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Static regression tests for VIOS request-body size enforcement.

The request handler is an implementation-local class in a large C++ translation
unit, so linking it into the existing gtest binary would require starting from
the full VIOS build. These tests instead compile the exact route-classification
method extracted from the production source and assert the size-policy control
flow directly. They run with only Python's standard library and a C++ compiler.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


VIOS_ROOT = Path(__file__).resolve().parents[2]
HANDLER_PATH = VIOS_ROOT / "src/framework/web/http_server/HttpServerRequestHandler.cpp"
UTILS_PATH = VIOS_ROOT / "src/framework/utilities/utils.cpp"


def _extract_braced_definition(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated definition: {signature}")


class HttpServerRequestHandlerPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = HANDLER_PATH.read_text(encoding="utf-8")
        cls.input_method = _extract_braced_definition(
            cls.source,
            "VmsErrorCode getInputMessage",
        )

    def test_post_and_put_upload_routes_with_optional_vst_prefix(self) -> None:
        """Compile and execute the production route matcher for the route matrix."""
        compiler = shutil.which("c++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("a C++ compiler is required for the route-matcher test")

        constants = "\n".join(
            line
            for line in self.source.splitlines()
            if line.startswith("constexpr char STORAGE_MANAGEMENT_UPLOAD_API")
            or line.startswith("constexpr const char* HTTP_METHOD_POST")
            or line.startswith("constexpr const char* HTTP_METHOD_PUT")
        )
        route_method = _extract_braced_definition(
            self.source,
            "bool isFileUploadAPI",
        )
        harness = f"""
#include <cstring>
{constants}
class RouteHarness {{
public:
{route_method}
}};
int main() {{
    RouteHarness handler;
    struct Case {{ const char* method; const char* uri; bool expected; }};
    const Case cases[] = {{
        {{"POST", "/api/v1/storage/file", true}},
        {{"POST", "/vst/api/v1/storage/file", true}},
        {{"PUT", "/api/v1/storage/file/example.mp4", true}},
        {{"PUT", "/vst/api/v1/storage/file/example.mp4", true}},
        {{"POST", "/api/v1/sensor/add", false}},
        {{"PUT", "/api/v1/sensor/add", false}},
    }};
    for (const auto& test : cases) {{
        if (handler.isFileUploadAPI(test.uri, test.method) != test.expected) {{
            return 1;
        }}
    }}
    return 0;
}}
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "route_policy_test.cpp"
            binary_path = Path(directory) / "route_policy_test"
            source_path.write_text(harness, encoding="utf-8")
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(source_path),
                    "-o",
                    str(binary_path),
                ],
                check=True,
            )
            subprocess.run([str(binary_path)], check=True)

    def test_upload_route_is_computed_once_before_raw_body_bypass(self) -> None:
        self.assertEqual(self.input_method.count("isFileUploadAPI("), 1)
        computed = self.input_method.index("const bool isUploadRequest")
        configured_limit = self.input_method.index(
            "config.nv_streamer_max_upload_file_size_MB"
        )
        bypass = self.input_method.index("Upload API, skip parsing message")
        json_limit = self.input_method.index(
            "const long long maxAllowedLength = MAX_JSON_CONTENT_LENGTH"
        )
        self.assertLess(computed, configured_limit)
        self.assertLess(configured_limit, bypass)
        self.assertLess(bypass, json_limit)

    def test_at_limit_upload_is_accepted_and_one_byte_over_is_413(self) -> None:
        over_limit = _extract_braced_definition(
            self.input_method,
            "if (contentLengthPolicy == UploadContentLengthPolicy::TooLarge)",
        )
        self.assertIn(
            "return VmsErrorCode::PayloadTooLargeError;",
            over_limit,
        )
        self.assertIn(
            "SET_VMS_ERROR2(VmsErrorCode::PayloadTooLargeError",
            over_limit,
        )

        error_mapping = UTILS_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            error_mapping,
            r"case PayloadTooLargeError:\s*return std::make_pair\(413,\s*"
            r'"Payload Too Large"\);',
        )

        self._compile_and_run_content_length_policy()

    def test_unknown_length_post_and_put_uploads_fail_closed(self) -> None:
        """POST multipart and raw PUT share the fail-closed upload branch."""
        unknown_length = _extract_braced_definition(
            self.input_method,
            "if (contentLengthPolicy == UploadContentLengthPolicy::Missing)",
        )
        upload_branch = _extract_braced_definition(
            self.input_method,
            "if (isUploadRequest)",
        )
        self.assertIn("Content-Length is required for file uploads", unknown_length)
        self.assertIn(
            "return VmsErrorCode::InvalidParameterError;",
            unknown_length,
        )
        self.assertIn("UploadContentLengthPolicy::Missing", upload_branch)
        self.assertIn("unknown-length raw PUT and multipart POST uploads", self.source)
        self.assertLess(
            self.input_method.index("UploadContentLengthPolicy::Missing"),
            self.input_method.index("Upload API, skip parsing message"),
        )

    def _compile_and_run_content_length_policy(self) -> None:
        """Execute the exact production policy at missing/limit/limit+1."""
        compiler = shutil.which("c++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("a C++ compiler is required for the size-policy test")

        enum_start = self.source.index("enum class UploadContentLengthPolicy")
        enum_end = self.source.index(";", enum_start) + 1
        policy_enum = self.source[enum_start:enum_end]
        policy_function = _extract_braced_definition(
            self.source,
            "constexpr UploadContentLengthPolicy validateUploadContentLength",
        )
        harness = f"""
{policy_enum}
{policy_function}
int main() {{
    constexpr long long limit = 1024;
    if (validateUploadContentLength(-1, limit) != UploadContentLengthPolicy::Missing) return 1;
    if (validateUploadContentLength(limit, limit) != UploadContentLengthPolicy::Allow) return 2;
    if (validateUploadContentLength(limit + 1, limit) != UploadContentLengthPolicy::TooLarge) return 3;
    return 0;
}}
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "content_length_policy_test.cpp"
            binary_path = Path(directory) / "content_length_policy_test"
            source_path.write_text(harness, encoding="utf-8")
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(source_path),
                    "-o",
                    str(binary_path),
                ],
                check=True,
            )
            subprocess.run([str(binary_path)], check=True)

    def test_non_upload_json_body_keeps_100kb_limit(self) -> None:
        self.assertIn(
            "constexpr int MAX_JSON_CONTENT_LENGTH = 100000;",
            self.source,
        )
        self.assertIn(
            "const long long maxAllowedLength = MAX_JSON_CONTENT_LENGTH;",
            self.input_method,
        )
        self.assertIn(
            "isValidContentLength(req_info->content_length, maxAllowedLength, "
            "req_info->request_method)",
            self.input_method,
        )


if __name__ == "__main__":
    unittest.main()
