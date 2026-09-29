import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import server


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class MediaPathTests(unittest.TestCase):
    @patch("server.urlopen")
    def test_recording_origin_comes_from_vios_timeline(self, urlopen):
        urlopen.return_value = _Response(json.dumps([{
            "startTime": "2025-01-01T00:00:00Z", "endTime": "2025-01-01T00:00:10Z"
        }]).encode())
        start = server.parse_timestamp("2025-01-01T00:00:03Z")
        end = server.parse_timestamp("2025-01-01T00:00:08Z")
        self.assertEqual(start.timestamp() - server.recording_start("recording", start, end), 3)

    @patch("server.subprocess.run")
    def test_output_duration_must_cover_the_requested_interval(self, run):
        with TemporaryDirectory() as directory:
            clip = Path(directory) / "clip.mp4"
            clip.write_bytes(b"clip")
            run.return_value.stdout = "1.0"
            with self.assertRaisesRegex(RuntimeError, "requested duration"):
                server.validate_output(clip, 5)
            run.return_value.stdout = "5.0"
            server.validate_output(clip, 5)
            run.return_value.stdout = "nan"
            with self.assertRaises(RuntimeError):
                server.validate_output(clip, 5)

    def test_resolves_both_media_roots_and_rejects_escape(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live"
            recorded = root / "recorded"
            live.mkdir()
            recorded.mkdir()
            (live / "camera.mp4").touch()
            (recorded / "upload.mp4").touch()
            (root / "outside.mp4").touch()
            (recorded / "escape.mp4").symlink_to(root / "outside.mp4")
            with patch.object(server, "MEDIA_ROOT", live), patch.object(server, "RECORDING_ROOT", recorded):
                self.assertEqual(server.local_media_path(server.VST_PATH_PREFIX + "/camera.mp4"), live / "camera.mp4")
                self.assertEqual(server.local_media_path(server.RECORDING_PATH_PREFIX + "/upload.mp4"), recorded / "upload.mp4")
                for suffix in ("/../outside.mp4", "/escape.mp4", "/missing.mp4"):
                    with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                        server.local_media_path(server.RECORDING_PATH_PREFIX + suffix)
                with self.assertRaises(ValueError):
                    server.local_media_path("/unapproved/upload.mp4")


class TextEmbeddingAdapterTests(unittest.TestCase):
    @patch("server.urlopen")
    def test_translates_cosmos_response_to_openai_embedding_contract(self, urlopen):
        urlopen.return_value = _Response(
            json.dumps(
                {
                    "data": [
                        {"embeddings": [0.1, 0.2], "text_input": "robot"},
                        {"embeddings": [0.3, 0.4], "text_input": "forklift"},
                    ]
                }
            ).encode()
        )

        result = server.generate_text_embeddings(
            {"input": ["robot", "forklift"], "input_type": "query"}
        )

        self.assertEqual(result["data"][0]["embedding"], [0.1, 0.2])
        self.assertEqual(result["data"][1]["index"], 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, server.COSMOS_EMBED_API_URL)
        self.assertEqual(
            json.loads(request.data),
            {"model": server.COSMOS_EMBED_MODEL, "text_input": ["robot", "forklift"]},
        )

    @patch("server.urlopen")
    def test_long_summary_keeps_tail_and_original_document_order(self, urlopen):
        urlopen.return_value = _Response(json.dumps({"data": [
            {"embeddings": [1.0, 0.0]}, {"embeddings": [0.0, 1.0]},
            {"embeddings": [0.3, 0.4]},
        ]}).encode())
        text = "a" * 1000 + "tail " * 100
        result = server.generate_text_embeddings({"input": [text, "short"]})
        sent = json.loads(urlopen.call_args.args[0].data)["text_input"]
        self.assertEqual("".join(sent[:2]), text)
        self.assertTrue(all(len(part) <= 1000 for part in sent))
        self.assertAlmostEqual(result["data"][0]["embedding"][0], 2 / (5 ** 0.5))
        self.assertAlmostEqual(result["data"][0]["embedding"][1], 1 / (5 ** 0.5))
        self.assertEqual(result["data"][1]["embedding"], [0.3, 0.4])
        self.assertEqual(result["data"][1]["index"], 1)

    @patch("server.urlopen")
    def test_large_documents_use_bounded_upstream_batches(self, urlopen):
        def respond(request, **_kwargs):
            texts = json.loads(request.data)["text_input"]
            self.assertLessEqual(len(texts), 50)
            self.assertTrue(all(len(text) <= 1000 for text in texts))
            return _Response(json.dumps({"data": [{"embeddings": [1.0, 0.0]} for _ in texts]}).encode())
        urlopen.side_effect = respond
        result = server.generate_text_embeddings({"input": ["x" * 32768, "y" * 32768]})
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(len(result["data"]), 2)

    @patch("server.urlopen")
    def test_rejects_nonfinite_vectors(self, urlopen):
        urlopen.return_value = _Response(json.dumps({"data": [{"embeddings": [float("nan")]}]}).encode())
        with self.assertRaises(RuntimeError):
            server.generate_text_embeddings({"input": "short"})

    def test_rejects_empty_or_oversized_batches(self):
        for payload in ({"input": []}, {"input": [""]}, {"input": ["x"] * 51}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                server.generate_text_embeddings(payload)


if __name__ == "__main__":
    unittest.main()
