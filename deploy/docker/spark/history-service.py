#!/usr/bin/env python3
"""CPU-only history maintenance beside the running agent; no producer restart."""
import os
from types import SimpleNamespace

from fastapi import FastAPI
import uvicorn

from vss_agents.api.history_clear import create_history_clear_router

app = FastAPI(title='Local VSS history maintenance')
config = SimpleNamespace(
    vst_url=os.environ['VST_INTERNAL_URL'].rstrip('/'),
    elasticsearch_url=os.environ['ELASTIC_SEARCH_ENDPOINT'].rstrip('/'),
    lvs_backend_url=os.environ['LVS_BACKEND_URL'].rstrip('/'),
    vst_streamprocessor_url=os.environ['VST_STREAMPROCESSOR_URL'].rstrip('/'),
)
app.include_router(create_history_clear_router(config))


@app.get('/health')
def health():
    return {'status': 'ok'}


if __name__ == '__main__':
    uvicorn.run(app, host=os.environ['HISTORY_SERVICE_HOST'], port=int(os.environ['HISTORY_SERVICE_PORT']))
