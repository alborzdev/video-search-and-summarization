import io
import base64
import json
import hashlib
import shutil
import subprocess
import os
import time
import unittest
import struct
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import server


class CacheHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.patch = patch.object(server, "CACHE_ROOT", self.root)
        self.patch.start()
        server.HISTORY_PLANS.clear()

    def tearDown(self):
        server.HISTORY_PLANS.clear()
        self.patch.stop()
        self.directory.cleanup()

    def old_clip(self, key):
        clip = self.root / f"{key}.mp4"
        metadata = clip.with_suffix(".json")
        clip.write_bytes(b"generated clip")
        metadata.write_text('{"sensorId":"camera"}')
        for path in (clip, metadata):
            os.utime(path, (time.time() - 60, time.time() - 60))
        return clip

    def preview(self):
        from datetime import datetime, timezone
        return server.preview_cache_history(datetime.now(timezone.utc).isoformat())

    def test_exact_snapshot_keeps_new_clips_and_is_idempotent(self):
        old = self.old_clip("a" * 64)
        plan = self.preview()
        fresh = self.old_clip("b" * 64)
        result = server.clear_cache_history(plan["planToken"])
        self.assertEqual(result, {"deleted": 1, "retained": 0})
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(server.clear_cache_history(plan["planToken"]), result)

    def test_regenerated_or_referenced_existing_key_is_retained(self):
        clip = self.old_clip("a" * 64)
        plan = self.preview()
        os.utime(clip, None)
        result = server.clear_cache_history(plan["planToken"])
        self.assertEqual(result, {"deleted": 0, "retained": 1})
        self.assertTrue(clip.exists())
        self.assertTrue(clip.with_suffix(".json").exists())

    def test_symlink_and_unrelated_files_are_retained(self):
        original = self.root / "settings.json"
        original.write_text("keep me")
        (self.root / f"{'a' * 64}.mp4").symlink_to(original)
        plan = self.preview()
        self.assertEqual(plan["count"], 0)
        self.assertEqual(plan["retained"], 1)
        self.assertTrue(original.exists())

    def test_expired_token_rejected_without_mutation(self):
        clip = self.old_clip("a" * 64)
        plan = self.preview()
        server.HISTORY_PLANS[plan["planToken"]]["expires"] = 0
        with self.assertRaises(ValueError):
            server.clear_cache_history(plan["planToken"])
        self.assertTrue(clip.exists())

    def test_cancel_releases_preview_without_removing_media(self):
        clip = self.old_clip("a" * 64)
        plan = self.preview()
        self.assertGreater(server.HISTORY_PLANS[plan["planToken"]]["expires"] - time.monotonic(), 25 * 60)
        self.assertEqual(server.cancel_cache_history(plan["planToken"]), {"status": "cancelled"})
        self.assertEqual(server.cancel_cache_history(plan["planToken"]), {"status": "cancelled"})
        self.assertTrue(clip.exists())
        self.assertFalse(server.HISTORY_PLANS)


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


class _NativeResponse(_Response):
    def __init__(self, content, headers=None):
        super().__init__(content)
        self.headers = headers or {}


class AppearanceCropTests(unittest.TestCase):
    sensor = "3688c328-7e71-493c-a1c7-011ad2fb3893"
    timestamp = "2026-10-01T15:50:49.791Z"
    png = b"\x89PNG\r\n\x1a\n" + b"test crop"

    def payload(self, **updates):
        payload = {"sensorId": self.sensor, "timestamp": self.timestamp,
                   "bbox": {"leftX": 100, "topY": 150, "rightX": 200, "bottomY": 350}}
        payload.update(updates)
        return payload

    def opener(self, data=b"\xff\xd8jpeg", headers=None):
        opener = Mock()
        opener.open.return_value = _NativeResponse(data, headers)
        return opener

    def export(self, command, **kwargs):
        self.assertLessEqual(kwargs["timeout"], 8)
        self.assertIn("-hwaccel", command)
        self.assertEqual(command[command.index("-hwaccel") + 1], "none")
        self.assertEqual(command[command.index("-frames:v") + 1], "1")
        self.assertEqual(command[command.index("-threads") + 1], "1")
        self.assertIn("scale=1280:720,crop=100:200:100:150:exact=1", command[command.index("-vf") + 1])
        Path(command[-1]).write_bytes(self.png)

    def test_raw_bbox_clamps_and_rejects_invalid_requests_before_network(self):
        payload = self.payload(bbox={"leftX": -5, "topY": -20, "rightX": 1300, "bottomY": 800})
        self.assertEqual(server.appearance_request(payload)[2], (0, 0, 1280, 720))
        invalid = [None, self.payload(sensorId="../../etc/passwd"),
                   self.payload(timestamp="2026-10-01T15:50:49"),
                   self.payload(bbox={"leftX": 1300, "topY": 0, "rightX": 1400, "bottomY": 10})]
        for value in (True, float("nan"), "100", None):
            box = self.payload()["bbox"]
            box["leftX"] = value
            invalid.append(self.payload(bbox=box))
        with patch.object(server, "build_opener") as opener:
            for payload in invalid:
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    server.generate_appearance_crop(payload)
            opener.assert_not_called()

    def test_fixed_origin_picture_becomes_bounded_cpu_png(self):
        opener = self.opener(headers={"Content-Length": "6"})
        with patch.object(server, "build_opener", return_value=opener), \
                patch.object(server.subprocess, "run", side_effect=self.export), \
                patch.object(server, "appearance_clip_frame") as fallback:
            result = server.generate_appearance_crop(self.payload())
        self.assertEqual(base64.b64decode(result["image_base64"]), self.png)
        request = opener.open.call_args.args[0]
        self.assertTrue(request.full_url.startswith(server.VST_API_URL + "/v1/replay/stream/" + self.sensor + "/picture?"))
        self.assertIn("startTime=2026-10-01T15%3A50%3A49.791000Z", request.full_url)
        fallback.assert_not_called()

    def test_bad_or_oversized_picture_uses_one_second_clip_fallback(self):
        for data, headers in ((b"not jpeg", {}), (b"\xff\xd8jpeg", {"Content-Length": "999999999"})):
            with self.subTest(data=data), patch.object(server, "build_opener", return_value=self.opener(data, headers)), \
                    patch.object(server, "appearance_clip_frame", return_value=Path("/cache/local.mp4")) as fallback, \
                    patch.object(server.subprocess, "run", side_effect=self.export):
                server.generate_appearance_crop(self.payload())
                self.assertEqual(fallback.call_args.args[:2], (self.sensor, "2026-10-01T15:50:49.791000Z"))

    def test_concurrent_crop_is_rejected_and_failed_crop_releases_slot(self):
        with server.APPEARANCE_LOCK:
            with self.assertRaises(server.AppearanceBusy):
                server.generate_appearance_crop(self.payload())
        with patch.object(server, "build_opener", return_value=self.opener()), \
                patch.object(server.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 8)):
            with self.assertRaises(subprocess.TimeoutExpired):
                server.generate_appearance_crop(self.payload())
        self.assertTrue(server.APPEARANCE_LOCK.acquire(blocking=False))
        server.APPEARANCE_LOCK.release()

    def test_fallback_timeout_kills_entire_child_group_and_releases_clip_lock(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [subprocess.TimeoutExpired("clip", 35), (b"", None)]
        with patch.object(server.subprocess, "Popen", return_value=process) as popen, \
                patch.object(server.os, "killpg") as kill:
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                server.appearance_clip_frame(self.sensor, self.timestamp, time.monotonic() + 50)
        kill.assert_called_once_with(123, server.signal.SIGKILL)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIn("cpu_only=True", popen.call_args.args[0][2])
        self.assertTrue(server.PREPARE_LOCK.acquire(blocking=False))
        server.PREPARE_LOCK.release()

    def test_http_route_and_request_size(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/appearance-crop"
        body = json.dumps(self.payload()).encode()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.json_response = Mock()
        with patch.object(server, "generate_appearance_crop", return_value={"image_base64": "PNG"}) as crop:
            handler.do_POST()
            crop.assert_called_once_with(self.payload())
        handler.json_response.assert_called_once_with(200, {"image_base64": "PNG"})
        handler.headers = {"Content-Length": "4097"}
        handler.json_response.reset_mock()
        handler.do_POST()
        self.assertEqual(handler.json_response.call_args.args[0], 422)

    @unittest.skipUnless(shutil.which("ffmpeg"), "CPU FFmpeg required")
    def test_real_ffmpeg_returns_one_png_with_bounded_crop_dimensions(self):
        with TemporaryDirectory() as directory:
            frame = Path(directory) / "frame.jpg"
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=1280x720:rate=1", "-frames:v", "1", "-threads", "1", str(frame),
            ], check=True, timeout=8, capture_output=True)
            with patch.object(server, "build_opener", return_value=self.opener(frame.read_bytes())):
                result = server.generate_appearance_crop(self.payload())
            png = base64.b64decode(result["image_base64"])
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", png[16:24]), (224, 448))
            self.assertLessEqual(len(png), server.MAX_APPEARANCE_PNG_BYTES)


class NativeRetentionTests(unittest.TestCase):
    start = "2026-09-30T02:39:51.469000Z"
    end = "2026-09-30T02:40:16.469000Z"

    def opener(self, content=b"native mp4", start=None, headers=None):
        opener = Mock()
        opener.open.side_effect = [
            _NativeResponse(json.dumps({
                "videoUrl": "http://advertised.example/vst/storage/temp_files/clip.mp4",
                "startTime": self.start if start is None else start,
            }).encode()),
            _NativeResponse(content, headers),
        ]
        return opener

    def test_native_url_cannot_select_remote_origin_or_escape_storage(self):
        with patch.object(server, "VST_API_URL", "http://127.0.0.1:30888/vst/api"):
            self.assertEqual(
                server.native_media_url("http://169.254.169.254/vst/storage/temp_files/clip.mp4"),
                "http://127.0.0.1:30888/vst/storage/temp_files/clip.mp4",
            )
            for value in (
                "file:///vst/storage/clip.mp4", "http://example.com/secrets.mp4",
                "/vst/storage/%2e%2e/secrets.mp4", "/vst/storage/clip.mkv",
                "/vst/storage/%252e%252e/secrets.mp4",
                "/vst/storage/folder%5c..%5cclip.mp4",
            ):
                with self.subTest(url=value), self.assertRaises(ValueError):
                    server.native_media_url(value)
        self.assertIsNone(server._NoRedirect().redirect_request(None, None, 302, "", {}, "http://example.com"))

    def test_retains_bytes_with_bounded_requests_and_exact_start_metadata(self):
        opener = self.opener(headers={"Content-Length": "10"})
        with TemporaryDirectory() as directory, patch.object(server, "build_opener", return_value=opener), \
                patch.object(server, "validate_output") as validate:
            candidate = Path(directory) / "candidate.mp4"
            server.retain_native_clip("camera", self.start, self.end, candidate, 25)
            self.assertEqual(candidate.read_bytes(), b"native mp4")
            validate.assert_called_once_with(candidate, 25)
            self.assertEqual(opener.open.call_count, 2)
            self.assertTrue(all(0 < call.kwargs["timeout"] <= 20 for call in opener.open.call_args_list))
            self.assertIn("transcode=full", opener.open.call_args_list[0].args[0].full_url)
            self.assertNotIn("advertised.example", opener.open.call_args_list[1].args[0].full_url)

    def test_rejects_wrong_interval_metadata_before_downloading(self):
        opener = self.opener(start="2026-09-30T02:39:52.469000Z")
        with TemporaryDirectory() as directory, patch.object(server, "build_opener", return_value=opener):
            candidate = Path(directory) / "candidate.mp4"
            with self.assertRaisesRegex(ValueError, "requested interval"):
                server.retain_native_clip("camera", self.start, self.end, candidate, 25)
            self.assertFalse(candidate.exists())
            self.assertEqual(opener.open.call_count, 1)

    def test_download_size_and_overall_time_are_bounded(self):
        with TemporaryDirectory() as directory:
            for headers in ({"Content-Length": "11"}, {}):
                with self.subTest(headers=headers), patch.object(server, "MAX_NATIVE_CLIP_BYTES", 5), \
                        patch.object(server, "build_opener", return_value=self.opener(headers=headers)):
                    with self.assertRaisesRegex(ValueError, "size limit"):
                        server.retain_native_clip("camera", self.start, self.end, Path(directory) / "clip.mp4", 25)
            with patch.object(server, "build_opener", return_value=self.opener()), \
                    patch.object(server.time, "monotonic", side_effect=[0, 46]):
                with self.assertRaises(TimeoutError):
                    server.retain_native_clip("camera", self.start, self.end, Path(directory) / "clip.mp4", 25)

    def test_incomplete_download_is_rejected_before_metadata_probe(self):
        with TemporaryDirectory() as directory, \
                patch.object(server, "build_opener", return_value=self.opener(headers={"Content-Length": "100"})), \
                patch.object(server, "validate_output") as validate:
            with self.assertRaisesRegex(ValueError, "incomplete"):
                server.retain_native_clip("camera", self.start, self.end, Path(directory) / "clip.mp4", 25)
            validate.assert_not_called()

    def test_native_failure_preserves_existing_recorded_media_fallback(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "recordings"
            cache = root / "cache"
            media.mkdir()
            source = media / "upload.mp4"
            source.write_bytes(b"recorded media")

            def export(command, **kwargs):
                Path(command[-1]).write_bytes(b"retained recording")

            with patch.object(server, "CACHE_ROOT", cache), patch.object(server, "RECORDING_ROOT", media), \
                    patch.object(server, "retain_native_clip", side_effect=RuntimeError("native unavailable")), \
                    patch.object(server, "get_media_paths", return_value=[source]), \
                    patch.object(server, "recording_start", return_value=server.parse_timestamp(self.start).timestamp()), \
                    patch.object(server.subprocess, "run", side_effect=export), patch.object(server, "validate_output"):
                key, _ = server.build_clip("camera", self.start, self.end)
            self.assertEqual((cache / f"{key}.mp4").read_bytes(), b"retained recording")
            self.assertEqual(json.loads((cache / f"{key}.json").read_text()), {"sensorId": "camera"})
            self.assertEqual(source.read_bytes(), b"recorded media")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "CPU FFmpeg required")
    def test_epoch_interval_retains_real_native_25_second_mp4_and_rejects_short_clip(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "native.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=32x32:rate=10",
                "-t", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(native),
            ], check=True, timeout=20, capture_output=True)
            contents = native.read_bytes()
            cache = root / "cache"
            with patch.object(server, "CACHE_ROOT", cache), \
                    patch.object(server, "build_opener", return_value=self.opener(contents)), \
                    patch.object(server, "get_media_paths", side_effect=AssertionError("Epoch MKV fallback must not run")):
                key, clip_start = server.build_clip("camera", self.start, self.end)
            expected_key = hashlib.sha256(f"v2\0camera\0{self.start}\0{self.end}".encode()).hexdigest()
            self.assertEqual(key, expected_key)
            self.assertEqual(clip_start, self.start)
            retained = cache / f"{key}.mp4"
            self.assertEqual(retained.read_bytes(), contents)
            server.validate_output(retained, 25)
            self.assertEqual(json.loads(retained.with_suffix(".json").read_text()), {"sensorId": "camera"})
            # The real probe must continue rejecting a shorter native export;
            # successful HTTP metadata alone cannot mark a clip retained.
            with patch.object(server, "build_opener", return_value=self.opener(contents)):
                with self.assertRaisesRegex(RuntimeError, "requested duration"):
                    server.retain_native_clip("camera", self.start, self.end, root / "wrong.mp4", 30)


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
