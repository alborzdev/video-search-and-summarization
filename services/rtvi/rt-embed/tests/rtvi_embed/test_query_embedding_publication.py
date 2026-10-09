# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Search-query media must not become an indexed ingestion result."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from api_models.captions import VlmQuery
from api_models.embeddings import VideoEmbeddingsQuery
from server.rtvi_stream_handler import RequestInfo, RTVIStreamHandler


def test_ingestion_publishes_by_default_and_query_can_opt_out():
    values = {"id": str(uuid4()), "model": "cosmos-embed1-448p-anomaly-detection"}
    assert VideoEmbeddingsQuery(**values).publish_results is True
    assert VideoEmbeddingsQuery(**values, publish_results=False).publish_results is False


@pytest.mark.parametrize("publish_results", [True, False])
def test_publication_policy_does_not_discard_http_results(publish_results):
    handler = object.__new__(RTVIStreamHandler)
    handler._kafka_enabled = True
    proto = SimpleNamespace(SerializeToString=lambda: b"embedding-protobuf")
    handler._chunk_result_to_vision_llm = Mock(return_value=(proto, None))
    handler._send_protobuf_to_kafka = Mock()
    handler._update_stream_fps = Mock()
    query = VlmQuery(id=str(uuid4()), model="test", prompt="dummy", publish_results=publish_results)
    request = RequestInfo(query=query, chunk_count=2)
    chunk = SimpleNamespace(
        chunk=SimpleNamespace(chunkIdx=0), decode_retry_count=0,
        decode_start_time=0, decode_end_time=0, vlm_start_time=0, vlm_end_time=0,
        asr_start_time=0, asr_end_time=0, vlm_model_output=None, error=None,
    )
    handler._on_vlm_chunk_response(chunk, request)
    assert request.processed_chunk_list == [chunk]
    if publish_results:
        handler._send_protobuf_to_kafka.assert_called_once_with(b"embedding-protobuf", chunk, request)
    else:
        handler._chunk_result_to_vision_llm.assert_not_called()
        handler._send_protobuf_to_kafka.assert_not_called()
