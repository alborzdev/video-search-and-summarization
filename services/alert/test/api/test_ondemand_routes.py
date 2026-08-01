# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for on-demand verification API routes (FastAPI endpoints).

The endpoint now returns HTTP 202 immediately and dispatches VLM work
to a background task.  VLM-related exceptions no longer surface via HTTP;
they are handled by DirectMediaHandler in the background.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
_web_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "alert-agent-web")
)
_repo_root = os.path.abspath(os.path.join(_web_root, ".."))


SAMPLE_MESSAGE = {
    "id": "ondemand-abc-123",
    "sensorId": "ondemand",
    "timestamp": "2025-01-01T00:00:00+00:00",
    "end": "2025-01-01T00:00:00+00:00",
    "category": "collision",
    "info": {
        "media_urls": ["http://host/video.mp4"],
        "media_type": "video",
    },
}


@pytest.fixture()
def mock_service():
    svc = MagicMock()
    svc.prepare.return_value = (SAMPLE_MESSAGE, "user prompt", "system prompt")
    svc.register.return_value = SimpleNamespace(correlation_id="job-server-123")
    svc.process_and_publish.return_value = None
    return svc


@pytest.fixture()
def client(mock_service):
    """Create a TestClient with the ondemand service dependency overridden."""
    saved_modules = {
        k: sys.modules.pop(k)
        for k in list(sys.modules)
        if k == "app" or k.startswith("app.")
    }
    saved_path = sys.path[:]

    sys.path = [p for p in sys.path if os.path.abspath(p) != _repo_root and p != ""]
    sys.path.insert(0, _web_root)
    try:
        from app.main import app
        from app.api.verification_routes import get_ondemand_service
        from app.service.ondemand_verification_service import AlertTypeNotFoundError as _Err
        from app.service.terminal_job_store import (
            JobAlreadyExistsError as _DuplicateErr,
            JobCapacityError as _CapacityErr,
        )
    except (ImportError, Exception) as exc:
        pytest.skip(f"FastAPI app not importable: {exc}")
    finally:
        sys.path = saved_path
        sys.modules.update(saved_modules)

    mock_service._AlertTypeNotFoundError = _Err
    mock_service._JobAlreadyExistsError = _DuplicateErr
    mock_service._JobCapacityError = _CapacityErr
    app.dependency_overrides[get_ondemand_service] = lambda: mock_service
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _post(client, payload=None):
    if payload is None:
        payload = {
            "category": "collision",
            "info": {
                "media_urls": ["http://host/video.mp4"],
                "media_type": "video",
            },
        }
    return client.post("/api/v1/verification/ondemand", json=payload)


# ---------------------------------------------------------------------------
# Happy path — 202 accepted
# ---------------------------------------------------------------------------

class TestOndemandHappyPath:

    def test_returns_202(self, client):
        resp = _post(client)
        assert resp.status_code == 202

    def test_response_has_correlationId(self, client):
        resp = _post(client)
        body = resp.json()
        assert body["correlationId"] == "job-server-123"
        assert body["correlationId"] != SAMPLE_MESSAGE["id"]
        assert body["status"] == "accepted"
        assert body["statusUrl"] == (
            "/api/v1/verification/ondemand/job-server-123"
        )
        assert "timestamp" in body

    def test_full_incident_payload_accepted(self, client):
        resp = _post(client, {
            "id": "incident-xyz",
            "sensorId": "cam-01",
            "timestamp": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T00:00:30Z",
            "category": "collision",
            "info": {"media_urls": ["http://host/v.mp4"], "media_type": "video"},
        })
        assert resp.status_code == 202

    def test_prepare_called_with_payload(self, client, mock_service):
        _post(client, {
            "category": "collision",
            "info": {"media_urls": ["http://host/video.mp4"], "media_type": "video"},
        })
        mock_service.prepare.assert_called_once()
        call_arg = mock_service.prepare.call_args[0][0]
        assert call_arg["category"] == "collision"
        assert call_arg["info"]["media_urls"] == ["http://host/video.mp4"]

    def test_background_task_dispatched(self, client, mock_service):
        _post(client)
        mock_service.register.assert_called_once_with()
        mock_service.process_and_publish.assert_called_once_with(
            mock_service.register.return_value,
            SAMPLE_MESSAGE,
            "user prompt",
            "system prompt",
        )

    def test_server_job_id_allocation_conflict_returns_409(self, client, mock_service):
        mock_service.register.side_effect = mock_service._JobAlreadyExistsError(
            "duplicate"
        )
        resp = _post(client)
        assert resp.status_code == 409
        assert resp.json()["error"] == "job_id_allocation_conflict"
        mock_service.process_and_publish.assert_not_called()

    def test_capacity_exhaustion_returns_503(self, client, mock_service):
        mock_service.register.side_effect = mock_service._JobCapacityError(
            "full"
        )
        resp = _post(client)
        assert resp.status_code == 503
        assert resp.json()["error"] == "job_capacity_exhausted"
        mock_service.process_and_publish.assert_not_called()


# ---------------------------------------------------------------------------
# Validation errors (422) — sync, before background dispatch
# ---------------------------------------------------------------------------

class TestOndemandValidation:

    def test_missing_category_returns_422(self, client):
        resp = _post(client, {
            "info": {"media_urls": ["http://host/video.mp4"], "media_type": "video"},
        })
        assert resp.status_code == 422

    def test_missing_info_returns_422(self, client):
        resp = _post(client, {"category": "collision"})
        assert resp.status_code == 422

    def test_empty_category_returns_422(self, client):
        resp = _post(client, {
            "category": "   ",
            "info": {"media_urls": ["http://host/video.mp4"], "media_type": "video"},
        })
        assert resp.status_code == 422

    def test_info_missing_media_urls_returns_422(self, client):
        resp = _post(client, {
            "category": "collision",
            "info": {"media_type": "video"},
        })
        assert resp.status_code == 422

    def test_info_empty_media_urls_returns_422(self, client):
        resp = _post(client, {
            "category": "collision",
            "info": {"media_urls": [], "media_type": "video"},
        })
        assert resp.status_code == 422

    def test_info_invalid_media_type_returns_422(self, client):
        resp = _post(client, {
            "category": "collision",
            "info": {"media_urls": ["http://host/video.mp4"], "media_type": "audio"},
        })
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client):
        resp = client.post("/api/v1/verification/ondemand", json={})
        assert resp.status_code == 422

    def test_category_too_long_returns_422(self, client):
        resp = _post(client, {
            "category": "x" * 101,
            "info": {"media_urls": ["http://host/video.mp4"], "media_type": "video"},
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Sync error mapping (prepare errors)
# ---------------------------------------------------------------------------

class TestOndemandPrepareErrors:

    def test_unknown_category_returns_400(self, client, mock_service):
        mock_service.prepare.side_effect = mock_service._AlertTypeNotFoundError("No prompt for 'xyz'")
        resp = _post(client)
        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == "error"
        assert body["error"] == "unknown_category"

    def test_value_error_returns_400(self, client, mock_service):
        mock_service.prepare.side_effect = ValueError("bad input")
        resp = _post(client)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    def test_no_background_task_on_prepare_error(self, client, mock_service):
        mock_service.prepare.side_effect = ValueError("fail")
        _post(client)
        mock_service.process_and_publish.assert_not_called()


# ---------------------------------------------------------------------------
# Error response structure
# ---------------------------------------------------------------------------

class TestErrorResponseStructure:

    def test_error_response_has_required_fields(self, client, mock_service):
        mock_service.prepare.side_effect = ValueError("err")
        resp = _post(client)
        body = resp.json()
        assert set(body.keys()) >= {"status", "error", "message", "timestamp"}
        assert body["status"] == "error"
        assert body["timestamp"].endswith("Z")


class TestTerminalStatusRoutes:

    def test_get_returns_retained_snapshot(self, client, mock_service):
        mock_service.get_status.return_value = {
            "correlationId": "job-1",
            "state": "completed",
            "terminal": True,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:01Z",
            "result": {
                "processingOutcome": "verified",
                "sinkDelivery": {
                    "transport": "elastic",
                    "outcome": "acknowledged",
                },
            },
        }
        resp = client.get("/api/v1/verification/ondemand/job-1")
        assert resp.status_code == 200
        assert resp.json()["state"] == "completed"

    def test_get_missing_returns_404(self, client, mock_service):
        mock_service.get_status.return_value = None
        resp = client.get("/api/v1/verification/ondemand/missing")
        assert resp.status_code == 404

    def test_accepted_cancel_returns_202(self, client, mock_service):
        mock_service.cancel.return_value = {
            "correlationId": "job-1",
            "state": "cancelled",
            "terminal": True,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:01Z",
            "cancellationAccepted": True,
        }
        resp = client.delete("/api/v1/verification/ondemand/job-1")
        assert resp.status_code == 202

    def test_publish_owned_cancel_returns_409(self, client, mock_service):
        mock_service.cancel.return_value = {
            "correlationId": "job-1",
            "state": "publishing",
            "terminal": False,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:01Z",
            "cancellationAccepted": False,
        }
        resp = client.delete("/api/v1/verification/ondemand/job-1")
        assert resp.status_code == 409
