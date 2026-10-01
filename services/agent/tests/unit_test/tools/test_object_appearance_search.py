# SPDX-License-Identifier: Apache-2.0
import importlib.util
import os
from pathlib import Path
import unittest
import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

path = Path(__file__).resolve().parents[3] / "src/vss_agents/tools/object_appearance_search.py"
spec = importlib.util.spec_from_file_location("appearance", path)
appearance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(appearance)


class AppearanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_visual_search_respects_window_source_and_footage_in_preparation_and_cached_results(self):
        start = datetime(2026, 10, 1, 18, 40, tzinfo=UTC)
        end = datetime(2026, 10, 1, 18, 55, tzinfo=UTC)
        reference = datetime(2026, 10, 1, 18, 52, tzinfo=UTC)
        bbox = {"leftX": 5, "topY": 8, "rightX": 20, "bottomY": 40}
        seed = {"timestamp": reference.isoformat(), "object_id": "816", "object_type": "Forklift", "bbox": bbox}
        es = AsyncMock()
        es.indices.exists.return_value = True
        es.exists.return_value = True

        def match(timestamp, **updates):
            return {"_score": 0.9, "_source": {
                "provider": appearance.PROVIDER, "sensor_id": "camera-a", "source_type": "rtsp",
                "object_id": "817", "object_type": "Forklift", "bbox": bbox,
                "timestamp": timestamp, **updates,
            }}

        es.search.side_effect = [
            {"hits": {"hits": [
                {"_source": {"object": {"id": "old"}, "timestamp": "2026-10-01T16:00:00Z", "end": "2026-10-01T16:01:00Z"}},
                {"_source": {"object": {"id": "new"}, "timestamp": "2026-10-01T18:39:00Z", "end": "2026-10-01T18:42:00Z"}},
            ]}},
            {"hits": {"hits": [
                match("2026-10-01T16:03:00Z"),
                match("2026-10-01T18:45:00Z", sensor_id="camera-b"),
                match("2026-10-01T18:45:00Z", source_type="video_file"),
                match("2026-10-01T18:40:01Z"),
                match("2026-10-01T18:54:59Z"),
            ]}},
        ]
        attributes = ModuleType("vss_agents.tools.attribute_search")
        attributes.AttributeSearchMetadata = SimpleNamespace
        attributes.AttributeSearchResult = SimpleNamespace
        with patch.dict(os.environ, {"VSS_OBJECT_APPEARANCE_ENABLED": "true"}), \
                patch.dict(sys.modules, {attributes.__name__: attributes}), \
                patch.object(appearance, "_detections", AsyncMock(return_value=[seed])) as detections, \
                patch.object(appearance, "_cached_vector", AsyncMock(return_value=[0.1] * 768)):
            kwargs = dict(object_id="816", es=es, reference_sensor_id="camera-a",
                          reference_sensor_name="Warehouse", reference_timestamp=reference,
                          verified_sensor_aliases=["camera-a", "Warehouse"], source_type="rtsp",
                          video_sources=["Warehouse"], timestamp_start=start, timestamp_end=end)
            result = await appearance.search_reference_appearance(**kwargs)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0].metadata.start_time, start.isoformat())
            self.assertEqual(result[1].metadata.end_time, end.isoformat())
            track_filters = es.search.call_args_list[0].kwargs["body"]["query"]["bool"]["filter"]
            self.assertIn({"range": {"end": {"gte": start.isoformat()}}}, track_filters)
            self.assertIn({"range": {"timestamp": {"lte": end.isoformat()}}}, track_filters)
            candidate_calls = detections.call_args_list[1:]
            self.assertTrue(candidate_calls)
            for call in candidate_calls:
                self.assertEqual(call.kwargs["timestamp_start"], start)
                self.assertEqual(call.kwargs["timestamp_end"], end)
            self.assertNotIn("old", [call.kwargs["object_id"] for call in candidate_calls])
            knn = es.search.call_args_list[-1].kwargs["body"]["knn"]["filter"]["bool"]["filter"]
            self.assertIn({"range": {"timestamp": {"gte": start.isoformat(), "lte": end.isoformat()}}}, knn)
            es.reset_mock()
            self.assertEqual(await appearance.search_reference_appearance(**{**kwargs, "video_sources": ["Other"]}), [])
            self.assertEqual(await appearance.search_reference_appearance(**{**kwargs, "source_type": "video_file"}), [])
            es.search.assert_not_called()

    async def test_candidate_detection_window_never_expands_selected_time_filter(self):
        es = AsyncMock()
        es.search.return_value = {"hits": {"hits": []}}
        start = datetime(2026, 10, 1, 18, 40, tzinfo=UTC)
        await appearance._detections(es, ["camera"], start, object_id="816", timestamp_start=start)
        window = es.search.call_args.kwargs["body"]["query"]["bool"]["filter"][1]["range"]["timestamp"]
        self.assertEqual(window["gte"], start.isoformat())
        es.reset_mock()
        self.assertEqual(await appearance._detections(
            es, ["camera"], start, object_id="816", timestamp_start=start + appearance.timedelta(seconds=3)
        ), [])
        es.search.assert_not_called()

    def test_provider_isolation_and_vector_validation(self):
        self.assertTrue(appearance.valid_vector([0.1] * 768))
        for invalid in ([0.1] * 1152, [0] * 768, [float("nan")] * 768, [0.1] * 256):
            self.assertFalse(appearance.valid_vector(invalid))
        self.assertNotEqual(
            appearance.document_id("camera-a", "523", "time"), appearance.document_id("camera-b", "523", "time")
        )
        self.assertNotEqual(
            appearance.document_id("camera-a", "523", "time"), appearance.document_id("camera-a", "523", "later")
        )

    async def test_disabled_provider_does_not_start_preparation(self):
        with patch.dict(os.environ, {"VSS_OBJECT_APPEARANCE_ENABLED": "false"}):
            result = await appearance.search_reference_appearance(object_id="523", es=AsyncMock())
        self.assertIsNone(result)

    async def test_exact_detection_filters_source_time_object_and_valid_bbox(self):
        from datetime import UTC
        from datetime import datetime

        es = AsyncMock()
        es.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "sensorId": "camera-a",
                            "timestamp": "2026-10-01T15:51:00Z",
                            "objects": [
                                {
                                    "id": "523",
                                    "type": "Person",
                                    "bbox": {"leftX": 5, "topY": 8, "rightX": 20, "bottomY": 40},
                                },
                                {
                                    "id": "other",
                                    "type": "Person",
                                    "bbox": {"leftX": 5, "topY": 8, "rightX": 20, "bottomY": 40},
                                },
                            ],
                        }
                    }
                ]
            }
        }
        result = await appearance._detections(
            es, ["camera-a"], datetime(2026, 10, 1, 15, 51, tzinfo=UTC), object_id="523"
        )
        self.assertEqual([x["object_id"] for x in result], ["523"])
        query = es.search.call_args.kwargs["body"]["query"]["bool"]["filter"]
        self.assertEqual(query[0], {"terms": {"sensorId.keyword": ["camera-a"]}})
        self.assertEqual(query[2]["nested"]["query"]["bool"]["filter"][0], {"term": {"objects.id.keyword": "523"}})
        self.assertEqual(query[1]["range"]["timestamp"]["gte"], "2026-10-01T15:50:59+00:00")

    async def test_cached_vectors_explicitly_retrieved_from_elasticsearch_9(self):
        es = AsyncMock()
        es.search.return_value = {"hits": {"hits": [{"_source": {"vector": [0.1] * 768}}]}}
        vector = await appearance._cached_vector(es, "selected-seed")
        self.assertEqual(len(vector), 768)
        body = es.search.call_args.kwargs["body"]
        self.assertFalse(body["_source"]["exclude_vectors"])
        self.assertEqual(body["query"], {"ids": {"values": ["selected-seed"]}})
        es.search.return_value = {"hits": {"hits": [{"_source": {}}]}}
        with self.assertRaises(ValueError):
            await appearance._cached_vector(es, "selected-seed")
