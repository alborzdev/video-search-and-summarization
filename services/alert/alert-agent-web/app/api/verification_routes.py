#!/usr/bin/env python3
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

"""
On-demand verification HTTP routes.

Returns HTTP 202 immediately with a correlationId.  VLM processing and
result publishing (Kafka / Elasticsearch) run in a background task via
DirectMediaHandler — identical to the Kafka-driven pipeline.
"""

from datetime import datetime, timezone
import threading

from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.responses import JSONResponse
from openai import BadRequestError

from ..schema.verification_schemas import (
    OnDemandAcceptedResponse,
    OnDemandVerificationRequest,
    VerificationErrorResponse,
    VerificationJobStatus,
)
from ..service.ondemand_verification_service import (
    AlertTypeNotFoundError,
    OnDemandVerificationService,
)
from ..service.terminal_job_store import (
    JobAlreadyExistsError,
    JobCapacityError,
)

router = APIRouter(prefix="/api/v1/verification", tags=["verification"])

_ondemand_service: OnDemandVerificationService = None
_ondemand_service_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_ondemand_service() -> OnDemandVerificationService:
    global _ondemand_service
    if _ondemand_service is None:
        with _ondemand_service_lock:
            if _ondemand_service is None:
                _ondemand_service = OnDemandVerificationService()
    return _ondemand_service


def _error_response(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "error": error,
            "message": message,
            "timestamp": _utc_now(),
        },
    )


@router.post(
    "/ondemand",
    response_model=OnDemandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Verify alert on demand",
    description=(
        "Async on-demand verification using category-based prompt lookup. "
        "Returns HTTP 202 with a correlationId immediately. "
        "VLM processing runs in the background and results are published "
        "to Kafka / Elasticsearch via the same sink as the Kafka pipeline."
    ),
    responses={
        202: {
            "description": "Verification request accepted for background processing",
            "model": OnDemandAcceptedResponse,
        },
        400: {
            "description": "Unknown category or invalid request",
            "model": VerificationErrorResponse,
        },
        409: {
            "description": "Server-generated job ID allocation conflict",
            "model": VerificationErrorResponse,
        },
        503: {
            "description": "Bounded job registry capacity exhausted",
            "model": VerificationErrorResponse,
        },
    },
)
async def verify_ondemand(
    payload: OnDemandVerificationRequest,
    background_tasks: BackgroundTasks,
    service: OnDemandVerificationService = Depends(get_ondemand_service),
) -> JSONResponse:
    try:
        message, user_prompt, system_prompt = service.prepare(
            payload.model_dump()
        )
    except AlertTypeNotFoundError as e:
        return _error_response(
            status.HTTP_400_BAD_REQUEST, "unknown_category", str(e)
        )
    except (ValueError, BadRequestError) as e:
        return _error_response(
            status.HTTP_400_BAD_REQUEST, "invalid_request", str(e)
        )

    try:
        job_handle = service.register()
    except JobAlreadyExistsError as e:
        return _error_response(
            status.HTTP_409_CONFLICT, "job_id_allocation_conflict", str(e)
        )
    except JobCapacityError:
        return _error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "job_capacity_exhausted",
            "On-demand verification capacity is currently exhausted",
        )
    except ValueError as e:
        return _error_response(
            status.HTTP_400_BAD_REQUEST, "invalid_correlation_id", str(e)
        )

    correlation_id = job_handle.correlation_id
    background_tasks.add_task(
        service.process_and_publish,
        job_handle,
        message,
        user_prompt,
        system_prompt,
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "accepted",
            "correlationId": correlation_id,
            "statusUrl": f"/api/v1/verification/ondemand/{correlation_id}",
            "message": "Verification request accepted for processing",
            "timestamp": _utc_now(),
        },
    )


@router.get(
    "/ondemand/{correlation_id}",
    response_model=VerificationJobStatus,
    summary="Get on-demand verification status",
    description=(
        "Return bounded process-local job status. Terminal records expire and "
        "are not durable across Alert Bridge restarts."
    ),
    responses={
        200: {"description": "Retained job status"},
        400: {
            "description": "Invalid correlation ID",
            "model": VerificationErrorResponse,
        },
        404: {
            "description": "Job not found or terminal receipt expired",
            "model": VerificationErrorResponse,
        },
    },
)
async def get_ondemand_status(
    correlation_id: str,
    service: OnDemandVerificationService = Depends(get_ondemand_service),
) -> JSONResponse:
    try:
        snapshot = service.get_status(correlation_id)
    except ValueError as e:
        return _error_response(
            status.HTTP_400_BAD_REQUEST, "invalid_correlation_id", str(e)
        )
    if snapshot is None:
        return _error_response(
            status.HTTP_404_NOT_FOUND,
            "job_not_found",
            "No retained on-demand verification job has that correlationId",
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=snapshot)


@router.delete(
    "/ondemand/{correlation_id}",
    response_model=VerificationJobStatus,
    summary="Cancel on-demand verification before sink publication",
    description=(
        "Cancellation is accepted only while queued or running. Once sink "
        "publication begins, cancellation is rejected to avoid a false "
        "guarantee that no event was delivered."
    ),
    responses={
        200: {
            "description": "Job was already cancelled",
            "model": VerificationJobStatus,
        },
        202: {
            "description": "Cancellation accepted before publication",
            "model": VerificationJobStatus,
        },
        400: {
            "description": "Invalid correlation ID",
            "model": VerificationErrorResponse,
        },
        404: {
            "description": "Job not found or terminal receipt expired",
            "model": VerificationErrorResponse,
        },
        409: {
            "description": "Publication already started or job is terminal",
            "model": VerificationJobStatus,
        },
    },
)
async def cancel_ondemand(
    correlation_id: str,
    service: OnDemandVerificationService = Depends(get_ondemand_service),
) -> JSONResponse:
    try:
        snapshot = service.cancel(correlation_id)
    except ValueError as e:
        return _error_response(
            status.HTTP_400_BAD_REQUEST, "invalid_correlation_id", str(e)
        )
    if snapshot is None:
        return _error_response(
            status.HTTP_404_NOT_FOUND,
            "job_not_found",
            "No retained on-demand verification job has that correlationId",
        )

    if snapshot.get("cancellationAccepted") is True:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED, content=snapshot
        )
    if snapshot.get("state") == "cancelled":
        # Idempotent repeat after the cancellation guarantee was established.
        return JSONResponse(status_code=status.HTTP_200_OK, content=snapshot)
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=snapshot)
