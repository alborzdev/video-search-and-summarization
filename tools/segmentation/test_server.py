"""Resident server contract tests; fake models, CPU images, ephemeral loopback."""

import base64
import http.client
import io
import json
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from tools.segmentation import server


TOKEN = "test-token-only-not-for-deployment"


def image_bytes(size=(20, 10), format="PNG", **kwargs):
    buffer = io.BytesIO()
    Image.new("RGB", size, "gray").save(buffer, format=format, **kwargs)
    return buffer.getvalue()


def payload(**kwargs):
    return json.dumps({"task": "segment", "object": "panel",
                       "image_base64": base64.b64encode(image_bytes()).decode(), **kwargs}).encode()


class ImageContractTests(unittest.TestCase):
    def test_strict_payload_rejects_paths_urls_modes_and_bad_base64(self):
        for raw in (payload(path="/tmp/image.png"), payload(url="https://example.com"),
                    payload(model="other"), payload(image_base64="data:image/png;base64,AAAA"),
                    payload(image_base64="é"), payload(task="other"),
                    payload(grounded_by="auto"), payload(presence="auto"),
                    payload(task="detect", grounded_by="point")):
            with self.subTest(raw=raw[:80]), self.assertRaises(server.RequestError):
                server.parse_payload(raw)

    def test_decode_and_fit_preserves_aspect_without_upscale(self):
        image, info = server.decode_image(image_bytes((2048, 1024)))
        self.assertEqual(image.size, (1024, 512))
        self.assertEqual((info["width"], info["height"]), (2048, 1024))
        self.assertTrue(info["resized"])
        small, info = server.decode_image(image_bytes())
        self.assertEqual(small.size, (20, 10))
        self.assertFalse(info["resized"])

    def test_exif_orientation_precedes_inference_fit(self):
        exif = Image.Exif()
        exif[274] = 6
        image, info = server.decode_image(image_bytes((40, 20), "JPEG", exif=exif))
        self.assertEqual((info["source_width"], info["source_height"]), (40, 20))
        self.assertEqual((info["width"], info["height"]), (20, 40))
        self.assertEqual(image.size, (20, 40))

    def test_dimensions_compressed_size_and_formats_are_bounded(self):
        with self.assertRaises(server.RequestError) as caught:
            server.parse_payload(payload(image_base64="A" * (((server.MAX_IMAGE_BYTES + 2) // 3) * 4 + 4)))
        self.assertEqual(caught.exception.status, 413)
        with self.assertRaises(server.RequestError) as caught:
            server.decode_image(image_bytes((4001, 4000)))
        self.assertEqual(caught.exception.status, 413)
        with self.assertRaises(server.RequestError) as caught:
            server.decode_image(image_bytes(format="GIF"))
        self.assertEqual(caught.exception.status, 415)

    def test_masks_are_real_binary_png_and_numpy_does_not_leak(self):
        mask = np.zeros((10, 20), dtype=bool)
        mask[1:8, 2:15] = True
        result = {"operation": "segment", "image": {"width": 20, "height": 10},
                  "raw_grounding": {"points": [{"x": .3, "y": .4}]},
                  "moondream_receipt": {"path": "/private/checkpoint"},
                  "segmenter_receipt": {"manifest": "unneeded"},
                  "objects": [{"point": [.3, .4], "mask": mask, "mask_metadata": {"score": .8}}]}
        encoded = server.encode_result(result, {"width": 20, "height": 10})
        json.dumps(encoded, allow_nan=False)
        self.assertNotIn("mask", encoded["objects"][0])
        self.assertNotIn("moondream_receipt", encoded)
        self.assertEqual(encoded["raw_grounding"], result["raw_grounding"])
        png = base64.b64decode(encoded["objects"][0]["mask_png_base64"])
        np.testing.assert_array_equal(np.asarray(Image.open(io.BytesIO(png))) > 0, mask)
        self.assertIs(result["objects"][0]["mask"], mask)


class RuntimeTests(unittest.TestCase):
    def test_readiness_waits_until_complete_factory_and_memory_check(self):
        entered, release = threading.Event(), threading.Event()
        bridge = Mock()
        def factory():
            entered.set()
            self.assertTrue(release.wait(2))
            return bridge
        runtime = server.Runtime(TOKEN, 20, factory=factory, fatal=Mock())
        runtime.check_memory = Mock()
        worker = threading.Thread(target=runtime.warm)
        worker.start()
        self.assertTrue(entered.wait(2))
        self.assertFalse(runtime.health()["ready"])
        self.assertTrue(runtime.health()["busy"])
        release.set()
        worker.join(2)
        self.assertTrue(runtime.health()["ready"])
        self.assertIs(runtime.bridge, bridge)
        self.assertEqual(runtime.check_memory.call_count, 2)

    def test_failed_factory_never_advertises_ready(self):
        fatal = Mock()
        runtime = server.Runtime(TOKEN, 20, factory=Mock(side_effect=RuntimeError("failed warmup")), fatal=fatal)
        runtime.check_memory = Mock()
        with patch.object(server.traceback, "print_exc"):
            runtime.warm()
        self.assertFalse(runtime.health()["ready"])
        self.assertEqual(runtime.health()["status"], "failed")
        fatal.assert_called_once()

    def test_saved_reserve_increase_and_admitted_floor_are_preserved(self):
        runtime = server.Runtime(TOKEN, 28)
        with patch.object(server, "reserve_gib", return_value=20), patch.object(server, "available_gib", return_value=30):
            with self.assertRaises(RuntimeError):
                runtime.check_memory()
        with patch.object(server, "reserve_gib", return_value=32), patch.object(server, "available_gib", return_value=40):
            runtime.check_memory()
        self.assertEqual(runtime.reserve, 32)

    def test_inference_defaults_to_real_point_and_preserves_presence_choice(self):
        bridge = Mock()
        bridge.segment.return_value = {"operation": "segment", "status": "no_detections",
            "image": {"width": 20, "height": 10}, "objects": [], "raw_grounding": {"points": []}}
        runtime = server.Runtime(TOKEN, 20)
        runtime.bridge = bridge
        runtime.check_memory = Mock()
        result = runtime.infer(payload(presence="query"))
        self.assertEqual(bridge.segment.call_args.kwargs, {"grounded_by": "point"})
        self.assertEqual(bridge.presence_mode, "query")
        self.assertEqual(result["model_identity"], server.IDENTITY)
        self.assertEqual(result["objects"], [])

    def test_request_memory_failure_marks_service_unready_and_exits(self):
        fatal = Mock()
        runtime = server.Runtime(TOKEN, 20, fatal=fatal)
        runtime.state = "ready"
        runtime.check_memory = Mock(side_effect=RuntimeError("low memory"))
        with self.assertRaises(server.RequestError) as caught:
            runtime.infer(payload())
        self.assertEqual(caught.exception.status, 503)
        self.assertFalse(runtime.health()["ready"])
        fatal.assert_called_once()

    def test_startup_uses_saved_reserve_without_extra_allowance(self):
        with patch.object(server, "reserve_gib", return_value=28), patch.object(server, "guard_active", return_value=True):
            with patch.object(server, "available_gib", return_value=27.9):
                with self.assertRaises(RuntimeError):
                    server.startup_admission()
            with patch.object(server, "available_gib", return_value=28):
                self.assertEqual(server.startup_admission(), 28)

    def test_watchdog_guard_loss_exits_only_this_runtime(self):
        fatal = Mock()
        runtime = server.Runtime(TOKEN, 20, fatal=fatal)
        runtime.check_memory = Mock()
        runtime.stopping.wait = Mock(return_value=False)
        with patch.object(server, "guard_active", return_value=False):
            runtime.watchdog()
        self.assertFalse(runtime.health()["ready"])
        self.assertEqual(runtime.health()["status"], "failed")
        fatal.assert_called_once()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.runtime = server.Runtime(TOKEN, 20, fatal=Mock())
        self.httpd = server.Server(("127.0.0.1", 0), self.runtime)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.httpd.server_address, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def headers(self):
        return {"Content-Type": "application/json", "X-VSS-Model-Token": TOKEN}

    def test_health_is_responsive_while_worker_gate_is_held(self):
        self.runtime.gate.acquire()
        try:
            status, response = self.request("GET", "/health")
            self.assertEqual(status, 200)
            self.assertFalse(response["ready"])
            self.assertTrue(response["busy"])
            self.assertEqual(self.request("GET", "/ready")[0], 503)
        finally:
            self.runtime.gate.release()

    def test_authentication_precedes_body_and_busy_is_nonblocking(self):
        self.runtime.state = "ready"
        self.assertEqual(self.request("POST", "/infer", payload(), {"Content-Type": "application/json"})[0], 401)
        self.runtime.gate.acquire()
        try:
            self.assertEqual(self.request("POST", "/infer", payload(), self.headers())[0], 429)
            self.assertEqual(self.request("GET", "/ready")[0], 200)
        finally:
            self.runtime.gate.release()

    def test_success_and_validation_error_release_gate(self):
        self.runtime.state = "ready"
        self.runtime.infer = Mock(return_value={"status": "ok", "objects": []})
        status, value = self.request("POST", "/infer", payload(), self.headers())
        self.assertEqual(status, 200)
        self.assertEqual(value["objects"], [])
        self.assertFalse(self.runtime.gate.locked())
        self.runtime.infer.side_effect = server.RequestError(400, "Invalid image")
        self.assertEqual(self.request("POST", "/infer", payload(), self.headers())[0], 400)
        self.assertFalse(self.runtime.gate.locked())


if __name__ == "__main__":
    unittest.main()
