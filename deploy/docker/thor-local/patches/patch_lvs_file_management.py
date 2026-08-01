#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Backport the missing LVS file-info proxy into the released 3.2.1 image."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Callable


DEFAULT_SERVER = Path("/opt/nvidia/via/via-engine/via_server.py")
DEFAULT_CLIENT = Path("/opt/nvidia/via/via-engine/rtvi_vlm_client.py")

SERVER_IP_IMPORT_OLD = """from datetime import datetime, timezone
from typing import Annotated, Optional
"""
SERVER_IP_IMPORT_NEW = """from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Annotated, Optional
"""

SERVER_GUARD_HELPERS_OLD = """

class ViaServer:
"""
SERVER_GUARD_HELPERS_NEW = """

def _strict_environment_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, str(default)).strip().lower()
    if raw in {"true", "1"}:
        return True
    if raw in {"false", "0"}:
        return False
    raise ValueError(f"{name} must be true, false, 1, or 0")


def _is_numeric_loopback(host: str) -> bool:
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _file_api_request_allowed(path: str, client_host: str, loopback_only: bool) -> bool:
    files_root = f"{API_PREFIX}/files"
    is_file_api = path == files_root or path.startswith(f"{files_root}/")
    return not loopback_only or not is_file_api or _is_numeric_loopback(client_host)


class ViaServer:
"""

SERVER_MIDDLEWARE_OLD = """        self._app.config["host"] = args.host
        self._app.config["port"] = args.port

        self._setup_routes()
"""
SERVER_MIDDLEWARE_NEW = """        self._app.config["host"] = args.host
        self._app.config["port"] = args.port
        file_api_loopback_only = _strict_environment_flag(
            "VIA_FILE_API_LOOPBACK_ONLY", False
        )
        self._file_api_allow_filename = _strict_environment_flag(
            "VIA_FILE_API_ALLOW_FILENAME", True
        )

        @self._app.middleware("http")
        async def restrict_file_api(request: Request, call_next):
            client_host = request.client.host if request.client else ""
            if not _file_api_request_allowed(
                request.url.path, client_host, file_api_loopback_only
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "The LVS Files API is restricted to loopback clients"},
                )
            return await call_next(request)

        self._setup_routes()
"""

SERVER_IMPORT_OLD = """    DeleteFileResponse,
    GenerateCaptionsRequest,
"""
SERVER_IMPORT_NEW = """    DeleteFileResponse,
    FileInfo,
    GenerateCaptionsRequest,
"""

SERVER_ROUTE_OLD = """            return rtvi_resp

        @self._app.delete(
            f"{API_PREFIX}/files/{{file_id}}",
"""
SERVER_ROUTE_NEW = """            return rtvi_resp

        @self._app.get(
            f"{API_PREFIX}/files/{{file_id}}",
            summary="Get file metadata (proxied to RTVI-VLM)",
            description="Returns metadata for a file from the RTVI-VLM backend.",
            responses={
                200: {"description": "Successful Response."},
                **add_common_error_responses(),
            },
            tags=["Files"],
        )
        async def get_video_file_info(
            file_id: Annotated[UUID, Path(description="File ID to inspect.")],
        ) -> FileInfo:
            file_id = str(file_id)
            logger.info("Received get file info request (RTVI proxy) for %s", file_id)
            try:
                return self._stream_handler._vlm_pipeline.get_file_info(file_id)
            except Exception as e:
                logger.error("RTVI-VLM get file info failed for %s: %s", file_id, e)
                raise ViaException(
                    f"Failed to get file metadata from RTVI-VLM: {e}",
                    getattr(e, "code", "InternalServerError"),
                    getattr(e, "status_code", 500),
                )

        @self._app.delete(
            f"{API_PREFIX}/files/{{file_id}}",
"""

SERVER_UPLOAD_OLD = """                    file_id=id,
                    sensor_name=sensor_name,
                )
"""
SERVER_UPLOAD_NEW = """                    file_id=id,
                    sensor_name=sensor_name,
                    upload_filename=file.filename if file else None,
                )
"""

SERVER_FILENAME_GUARD_OLD = """        ) -> AddFileInfoResponse:
            logger.info(
"""
SERVER_FILENAME_GUARD_NEW = """        ) -> AddFileInfoResponse:
            if filename and not self._file_api_allow_filename:
                raise ViaException(
                    "The filename source is disabled; upload multipart file content instead",
                    "Forbidden",
                    403,
                )
            logger.info(
"""

CLIENT_SIGNATURE_OLD = """        file_id=None,
        sensor_name="",
    ):
"""
CLIENT_SIGNATURE_NEW = """        file_id=None,
        sensor_name="",
        upload_filename=None,
    ):
"""

CLIENT_FILENAME_OLD = """            fname = getattr(file_obj_or_path, "filename", "upload")
"""
CLIENT_FILENAME_NEW = """            fname = upload_filename or getattr(file_obj_or_path, "filename", "upload")
"""

CLIENT_OLD = '''    def delete_file(self, file_id):
        """Delete a file on RTVI-VLM via DELETE /v1/files/{file_id}.
'''
CLIENT_NEW = '''    def get_file_info(self, file_id):
        """Get file metadata from RTVI-VLM via GET /v1/files/{file_id}.

        Sticky-routed so the request reaches the same RTVI replica that owns
        the asset.
        """
        logger.info("RTVI get_file_info: x-stream-id=%s", file_id)
        resp = self._session.get(
            f"{self._base_url}/v1/files/{file_id}",
            timeout=RTVI_HEALTH_TIMEOUT,
            headers={"x-stream-id": str(file_id)},
        )
        if resp.status_code != 200:
            self._raise_rtvi_error("get file info", resp)
        return resp.json()

    def delete_file(self, file_id):
        """Delete a file on RTVI-VLM via DELETE /v1/files/{file_id}.
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one LVS {label} patch marker, found {count}")
    return source.replace(old, new, 1)


def patch_server_source(source: str) -> str:
    source = _replace_once(
        source, SERVER_IP_IMPORT_OLD, SERVER_IP_IMPORT_NEW, "server IP import"
    )
    source = _replace_once(
        source,
        SERVER_GUARD_HELPERS_OLD,
        SERVER_GUARD_HELPERS_NEW,
        "server guard helpers",
    )
    source = _replace_once(
        source, SERVER_MIDDLEWARE_OLD, SERVER_MIDDLEWARE_NEW, "server middleware"
    )
    source = _replace_once(
        source, SERVER_IMPORT_OLD, SERVER_IMPORT_NEW, "server import"
    )
    source = _replace_once(
        source, SERVER_UPLOAD_OLD, SERVER_UPLOAD_NEW, "server upload filename"
    )
    source = _replace_once(
        source,
        SERVER_FILENAME_GUARD_OLD,
        SERVER_FILENAME_GUARD_NEW,
        "server filename guard",
    )
    source = _replace_once(source, SERVER_ROUTE_OLD, SERVER_ROUTE_NEW, "server route")
    ast.parse(source)
    return source


def patch_client_source(source: str) -> str:
    source = _replace_once(
        source, CLIENT_SIGNATURE_OLD, CLIENT_SIGNATURE_NEW, "client upload signature"
    )
    source = _replace_once(
        source, CLIENT_FILENAME_OLD, CLIENT_FILENAME_NEW, "client upload filename"
    )
    source = _replace_once(source, CLIENT_OLD, CLIENT_NEW, "client method")
    ast.parse(source)
    return source


def patch_file(path: Path, transform: Callable[[str], str], suffix: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"LVS patch target is not a regular file: {path}")
    before = path.stat(follow_symlinks=False)
    source = path.read_text(encoding="utf-8")
    after = path.stat(follow_symlinks=False)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RuntimeError("LVS patch target changed while it was being read")
    patched = transform(source)

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=suffix,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(patched)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(before.st_mode), follow_symlinks=False)
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    if len(argv) not in {1, 3}:
        raise RuntimeError(
            "usage: patch_lvs_file_management.py [VIA_SERVER_PATH RTVI_CLIENT_PATH]"
        )
    server = Path(argv[1]) if len(argv) == 3 else DEFAULT_SERVER
    client = Path(argv[2]) if len(argv) == 3 else DEFAULT_CLIENT
    patch_file(server, patch_server_source, ".thor-file-management")
    patch_file(client, patch_client_source, ".thor-file-management")
    if server == DEFAULT_SERVER and client == DEFAULT_CLIENT:
        Path(__file__).unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
