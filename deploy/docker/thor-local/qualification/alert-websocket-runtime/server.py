#!/usr/bin/env python3
"""Minimal host for the exact mounted NVIDIA alert WebSocket modules."""

from __future__ import annotations

from contextlib import asynccontextmanager
import importlib
import sys

from fastapi import FastAPI
import uvicorn


sys.path.insert(0, "/app")
routes = importlib.import_module("alert-agent-web.app.websocket.websocket_routes")
service_module = importlib.import_module(
    "alert-agent-web.app.websocket.websocket_service"
)
websocket_service = service_module.websocket_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    await websocket_service.start()
    try:
        yield
    finally:
        await websocket_service.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(routes.router)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=19080, log_level="warning")
