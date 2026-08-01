# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Self-contained route tests with no Alert Bridge runtime dependencies."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import threading
import types

from pydantic import BaseModel, ConfigDict
from fastapi import FastAPI


class _Request(BaseModel):
    category: str
    info: dict
    model_config = ConfigDict(extra="allow")


class _AlertTypeNotFoundError(Exception):
    pass


class _JobAlreadyExistsError(ValueError):
    pass


class _JobCapacityError(RuntimeError):
    pass


def _load_routes():
    route_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "alert-agent-web",
            "app",
            "api",
            "verification_routes.py",
        )
    )
    schema_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "alert-agent-web",
            "app",
            "schema",
            "verification_schemas.py",
        )
    )
    root_name = "_isolated_verification_app"
    module_names = {
        root_name: types.ModuleType(root_name),
        f"{root_name}.api": types.ModuleType(f"{root_name}.api"),
        f"{root_name}.schema": types.ModuleType(f"{root_name}.schema"),
        f"{root_name}.service": types.ModuleType(f"{root_name}.service"),
        f"{root_name}.schema.verification_schemas": types.ModuleType(
            f"{root_name}.schema.verification_schemas"
        ),
        f"{root_name}.service.ondemand_verification_service": types.ModuleType(
            f"{root_name}.service.ondemand_verification_service"
        ),
        f"{root_name}.service.terminal_job_store": types.ModuleType(
            f"{root_name}.service.terminal_job_store"
        ),
    }
    module_names[root_name].__path__ = []
    module_names[f"{root_name}.api"].__path__ = []
    module_names[f"{root_name}.schema"].__path__ = []
    module_names[f"{root_name}.service"].__path__ = []
    service_module = module_names[
        f"{root_name}.service.ondemand_verification_service"
    ]
    service_module.AlertTypeNotFoundError = _AlertTypeNotFoundError
    service_module.OnDemandVerificationService = type(
        "OnDemandVerificationService", (), {}
    )
    job_module = module_names[f"{root_name}.service.terminal_job_store"]
    job_module.JobAlreadyExistsError = _JobAlreadyExistsError
    job_module.JobCapacityError = _JobCapacityError

    saved = {name: sys.modules.get(name) for name in module_names}
    openai_saved = sys.modules.get("openai")
    try:
        sys.modules.update(module_names)
        schema_spec = importlib.util.spec_from_file_location(
            f"{root_name}.schema.verification_schemas", schema_path
        )
        schema_module = importlib.util.module_from_spec(schema_spec)
        sys.modules[schema_spec.name] = schema_module
        schema_spec.loader.exec_module(schema_module)
        try:
            from openai import BadRequestError  # noqa: F401
        except (ImportError, ModuleNotFoundError):
            openai_stub = types.ModuleType("openai")
            openai_stub.BadRequestError = type(
                "BadRequestError", (Exception,), {}
            )
            sys.modules["openai"] = openai_stub

        spec = importlib.util.spec_from_file_location(
            f"{root_name}.api.verification_routes", route_path
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        if openai_saved is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = openai_saved


routes = _load_routes()


def _json(response):
    return json.loads(response.body.decode("utf-8"))


def _run(coroutine):
    return asyncio.run(coroutine)


class _BackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, function, *args):
        self.tasks.append((function, args))


class _Service:
    def __init__(self):
        self.message = {
            "id": "caller-event-id",
            "category": "collision",
            "info": {"media_urls": ["http://fixture/video.mp4"]},
        }
        self.status = None
        self.cancellation = None
        self.registration_count = 0

    def prepare(self, payload):
        return self.message, "prompt", "system"

    def register(self):
        self.registration_count += 1
        return types.SimpleNamespace(
            correlation_id=f"job-server-{self.registration_count}"
        )

    def process_and_publish(self, *args):
        raise AssertionError("background task must not run in a route unit test")

    def get_status(self, correlation_id):
        return self.status

    def cancel(self, correlation_id):
        return self.cancellation


def _payload():
    return _Request(
        category="collision",
        info={"media_urls": ["http://fixture/video.mp4"], "media_type": "video"},
    )


def test_post_registers_before_dispatch_and_returns_status_url():
    service = _Service()
    background = _BackgroundTasks()
    response = _run(routes.verify_ondemand(_payload(), background, service))

    assert response.status_code == 202
    assert service.registration_count == 1
    assert len(background.tasks) == 1
    assert _json(response)["statusUrl"] == (
        "/api/v1/verification/ondemand/job-server-1"
    )
    assert _json(response)["correlationId"] == "job-server-1"
    assert _json(response)["correlationId"] != service.message["id"]
    _, task_args = background.tasks[0]
    assert task_args[0].correlation_id == "job-server-1"
    assert task_args[1]["id"] == "caller-event-id"


def test_same_caller_event_id_gets_distinct_server_job_ids():
    service = _Service()
    first = _run(
        routes.verify_ondemand(_payload(), _BackgroundTasks(), service)
    )
    second = _run(
        routes.verify_ondemand(_payload(), _BackgroundTasks(), service)
    )
    assert _json(first)["correlationId"] == "job-server-1"
    assert _json(second)["correlationId"] == "job-server-2"
    assert _json(first)["correlationId"] != _json(second)["correlationId"]


def test_service_singleton_initialization_is_thread_safe():
    original_class = routes.OnDemandVerificationService
    original_service = routes._ondemand_service
    created = []
    constructor_entered = threading.Barrier(8)
    release_constructor = threading.Event()

    class _SlowService:
        def __init__(self):
            created.append(self)
            # If initialization were unlocked, all eight callers would enter.
            # With the lock, only one does; the barrier times out deliberately
            # and then the event makes completion deterministic.
            try:
                constructor_entered.wait(timeout=0.05)
            except threading.BrokenBarrierError:
                pass
            release_constructor.wait(timeout=1)

    routes.OnDemandVerificationService = _SlowService
    routes._ondemand_service = None
    start = threading.Barrier(9)
    results = []

    def resolve():
        start.wait()
        results.append(routes.get_ondemand_service())

    threads = [threading.Thread(target=resolve) for _ in range(8)]
    try:
        for thread in threads:
            thread.start()
        start.wait()
        # Give an unsafe implementation enough time to admit all constructors.
        release_constructor.wait(timeout=0.1)
        release_constructor.set()
        for thread in threads:
            thread.join(timeout=1)
        assert all(not thread.is_alive() for thread in threads)
        assert len(created) == 1
        assert len(results) == 8
        assert all(result is created[0] for result in results)
    finally:
        release_constructor.set()
        routes.OnDemandVerificationService = original_class
        routes._ondemand_service = original_service


def test_post_invalid_registration_returns_400_without_dispatch():
    service = _Service()
    service.register = lambda: (_ for _ in ()).throw(
        ValueError("invalid correlation")
    )
    background = _BackgroundTasks()
    response = _run(routes.verify_ondemand(_payload(), background, service))

    assert response.status_code == 400
    assert _json(response)["error"] == "invalid_correlation_id"
    assert background.tasks == []


def test_post_registration_conflict_and_capacity_are_documented_errors():
    service = _Service()
    service.register = lambda: (_ for _ in ()).throw(
        _JobAlreadyExistsError("server ID collision")
    )
    response = _run(
        routes.verify_ondemand(_payload(), _BackgroundTasks(), service)
    )
    assert response.status_code == 409
    assert _json(response)["error"] == "job_id_allocation_conflict"

    service.register = lambda: (_ for _ in ()).throw(
        _JobCapacityError("full")
    )
    response = _run(
        routes.verify_ondemand(_payload(), _BackgroundTasks(), service)
    )
    assert response.status_code == 503
    assert _json(response)["error"] == "job_capacity_exhausted"


def test_openapi_has_typed_success_error_and_conflict_contracts():
    app = FastAPI()
    app.include_router(routes.router)
    document = app.openapi()
    post = document["paths"]["/api/v1/verification/ondemand"]["post"]
    get = document["paths"][
        "/api/v1/verification/ondemand/{correlation_id}"
    ]["get"]
    delete = document["paths"][
        "/api/v1/verification/ondemand/{correlation_id}"
    ]["delete"]

    assert post["responses"]["202"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/OnDemandAcceptedResponse")
    for code in ("400", "409", "503"):
        assert post["responses"][code]["content"]["application/json"][
            "schema"
        ]["$ref"].endswith("/VerificationErrorResponse")
    assert get["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/VerificationJobStatus")
    for code in ("400", "404"):
        assert get["responses"][code]["content"]["application/json"][
            "schema"
        ]["$ref"].endswith("/VerificationErrorResponse")
    assert delete["responses"]["409"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/VerificationJobStatus")
    for code in ("200", "202"):
        assert delete["responses"][code]["content"]["application/json"][
            "schema"
        ]["$ref"].endswith("/VerificationJobStatus")


def test_get_status_200_400_and_404():
    service = _Service()
    service.status = {
        "correlationId": "job-123",
        "state": "completed",
        "terminal": True,
    }
    response = _run(routes.get_ondemand_status("job-123", service))
    assert response.status_code == 200
    assert _json(response)["state"] == "completed"

    service.status = None
    response = _run(routes.get_ondemand_status("missing", service))
    assert response.status_code == 404

    service.get_status = lambda correlation_id: (_ for _ in ()).throw(
        ValueError("invalid correlation")
    )
    response = _run(routes.get_ondemand_status("invalid", service))
    assert response.status_code == 400


def test_delete_status_202_200_400_404_and_409():
    service = _Service()
    base = {
        "correlationId": "job-123",
        "terminal": True,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:01Z",
    }

    service.cancellation = {
        **base,
        "state": "cancelled",
        "cancellationAccepted": True,
    }
    assert _run(routes.cancel_ondemand("job-123", service)).status_code == 202

    service.cancellation = {
        **base,
        "state": "cancelled",
        "cancellationAccepted": False,
    }
    assert _run(routes.cancel_ondemand("job-123", service)).status_code == 200

    service.cancellation = {
        **base,
        "state": "publishing",
        "terminal": False,
        "cancellationAccepted": False,
    }
    assert _run(routes.cancel_ondemand("job-123", service)).status_code == 409

    service.cancellation = None
    assert _run(routes.cancel_ondemand("missing", service)).status_code == 404

    service.cancel = lambda correlation_id: (_ for _ in ()).throw(
        ValueError("invalid correlation")
    )
    assert _run(routes.cancel_ondemand("invalid", service)).status_code == 400
