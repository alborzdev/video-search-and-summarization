"""CPU-only contract checks for the TensorRT engine build command."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_engine


class BuildEngineCommand(unittest.TestCase):
    def test_workspace_uses_trtexec_unitless_mib(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            model = directory / "models" / "rfdetr-small"
            model.mkdir(parents=True)
            (directory / "runtime").mkdir()
            graph = model / "rfdetr-small.onnx"
            graph.write_bytes(b"fixture")
            (model / "export-receipt.json").write_text(json.dumps({
                "onnxSha256": build_engine.digest(graph), "dynamicBatch": True,
                "spatialResolution": 512,
            }))
            process = mock.Mock(returncode=1)
            process.poll.return_value = 1
            with mock.patch.object(build_engine, "state_dir", return_value=directory), \
                 mock.patch.object(build_engine, "hardware_inventory", return_value={"platform": "spark"}), \
                 mock.patch.object(build_engine, "ensure_headroom"), \
                 mock.patch.object(build_engine.subprocess, "check_output", return_value='[{"Id":"image"}]'), \
                 mock.patch.object(build_engine.subprocess, "Popen", return_value=process) as popen:
                with self.assertRaisesRegex(RuntimeError, "Engine build failed"):
                    build_engine.build("spark", "small")
            command = popen.call_args.args[0]
            # trtexec's default unit is MiB; "2048MiB" is parsed as 2 KiB.
            self.assertIn("--memPoolSize=workspace:2048", command)
            self.assertEqual(sum(arg.startswith("--memPoolSize=") for arg in command), 1)


if __name__ == "__main__":
    unittest.main()
