"""Use real FastAPI/NAT lifespans to verify managed streaming task ownership."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.api import rtsp_ingest
from vss_agents.api.custom_fastapi_worker import CustomFastApiFrontEndWorker
from vss_agents.api.front_end_config import StreamingIngestConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("startup_failure", [False, True])
async def test_nat_lifespan_drains_managed_tasks_registered_during_startup(monkeypatch, startup_failure):
    monkeypatch.setattr(rtsp_ingest, "_embedding_bootstrap_tasks", set())
    monkeypatch.setattr(rtsp_ingest, "_embedding_generation_tasks", {})
    monkeypatch.setattr(rtsp_ingest, "_embedding_connected_streams", set())
    events = []
    bootstrap_started = asyncio.Event()
    managed_started = asyncio.Event()

    async def run_until_shutdown(name, started):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            events.append(f"{name}-closed")

    async def resume(_config):
        await run_until_shutdown("bootstrap", bootstrap_started)

    monkeypatch.setattr(rtsp_ingest, "resume_registered_embedding_generation", resume)
    config = SimpleNamespace(
        general=SimpleNamespace(
            front_end=SimpleNamespace(
                streaming_ingest=StreamingIngestConfig(vst_internal_url="http://vst.test:30888"),
            ),
        ),
    )
    worker = object.__new__(CustomFastApiFrontEndWorker)
    worker._config = config
    worker.set_cors_config = MagicMock()
    worker.cleanup_session_managers = AsyncMock(side_effect=lambda: events.append("nat-sessions-closed"))
    worker.cleanup_evaluators = AsyncMock(side_effect=lambda: events.append("nat-evaluators-closed"))

    async def configure(app, _builder):
        # This is NAT's real ordering: routes arrive after its lifespan entered.
        rtsp_ingest.register_rtsp_ingest_routes(app, config)
        rtsp_ingest._embedding_generation_tasks["camera"] = asyncio.create_task(
            run_until_shutdown("managed", managed_started),
        )
        await asyncio.wait_for(
            asyncio.gather(bootstrap_started.wait(), managed_started.wait()),
            timeout=1,
        )
        if startup_failure:
            raise RuntimeError("later startup step failed")

    worker.configure = AsyncMock(side_effect=configure)

    @asynccontextmanager
    async def builder_context():
        try:
            yield object()
        finally:
            events.append("builder-closed")

    with patch(
        "nat.front_ends.fastapi.fastapi_front_end_plugin_worker.WorkflowBuilder.from_config",
        return_value=builder_context(),
    ):
        app = worker.build_app()
        if startup_failure:
            with pytest.raises(RuntimeError, match="later startup step failed"):
                async with app.router.lifespan_context(app):
                    pytest.fail("failed startup must not yield a running app")
        else:
            async with app.router.lifespan_context(app):
                assert rtsp_ingest._embedding_bootstrap_tasks
                assert rtsp_ingest._embedding_generation_tasks

    assert not rtsp_ingest._embedding_bootstrap_tasks
    assert not rtsp_ingest._embedding_generation_tasks
    assert events.count("bootstrap-closed") == 1
    assert events.count("managed-closed") == 1
    if not startup_failure:
        worker.cleanup_session_managers.assert_awaited_once()
        worker.cleanup_evaluators.assert_awaited_once()
        assert events.index("managed-closed") < events.index("nat-sessions-closed")
        assert events.index("bootstrap-closed") < events.index("builder-closed")
