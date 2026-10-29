"""Small CPU numerical checks for the independent official-model loader."""

from pathlib import Path
from types import SimpleNamespace
import unittest

import torch

from tools.moondream.reference_loader import (
    _dequantize_expert,
    _import_reference,
    _validate_mapping,
)


class ReferenceLoaderTests(unittest.TestCase):
    def test_channel_scales_and_half_split_rows(self):
        raw = torch.tensor(
            [[1, 2], [3, 4], [5, 6], [7, 8]], dtype=torch.float8_e4m3fn
        )
        scale = torch.tensor([0.5, 0.25, 2.0, 4.0], dtype=torch.float32)
        result = _dequantize_expert(torch, raw, scale)
        expected = torch.tensor(
            [[0.5, 1], [0.75, 1], [10, 12], [28, 32]], dtype=torch.bfloat16
        )
        self.assertTrue(torch.equal(result, expected))
        # First two and last two rows remain separate halves: no Photon layout.
        self.assertTrue(torch.equal(result.chunk(2)[0], expected[:2]))

    def _tiny_mapping_case(self):
        model = torch.nn.Module()
        model.config = SimpleNamespace(text=SimpleNamespace(n_layers=0))
        model.register_parameter("expert", torch.nn.Parameter(torch.empty(2, 4, 3)))
        weights = {
            "raw": torch.zeros(2, 4, 3, dtype=torch.float8_e4m3fn),
            "scale": torch.ones(2, 4, dtype=torch.float32),
        }
        mapping = {"expert": ("raw", "scale", False)}
        return model, weights, mapping

    def test_unknown_checkpoint_tensor_is_rejected(self):
        model, weights, mapping = self._tiny_mapping_case()
        weights["unexpected"] = torch.zeros(1)
        with self.assertRaisesRegex(ValueError, "unrecognized_checkpoint_keys"):
            _validate_mapping(torch, model, weights, mapping)

    def test_bad_scale_and_bad_shape_are_rejected(self):
        model, weights, mapping = self._tiny_mapping_case()
        weights["scale"][0, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "Nonpositive or nonfinite"):
            _validate_mapping(torch, model, weights, mapping)
        weights["scale"].fill_(1)
        weights["raw"] = torch.zeros(2, 3, 4, dtype=torch.float8_e4m3fn)
        with self.assertRaisesRegex(ValueError, "Shape mismatch"):
            _validate_mapping(torch, model, weights, mapping)

    def test_official_decode_and_prefill_match_independent_expert_math(self):
        state = Path(__file__).resolve().parents[2] / ".spark/moondream-photon"
        source = Path((state / "reference-source-path.txt").read_text().strip())
        module, _, _ = _import_reference(source)
        import importlib
        layers = importlib.import_module(module.__package__ + ".layers")
        torch.manual_seed(72)
        # Test one-token bmm and multi-token F.linear/index_add code paths.
        for tokens in (1, 3):
            with self.subTest(tokens=tokens):
                batch, channels, inner, experts, active = 1, 16, 8, 4, 2
                x = torch.randn(batch, tokens, channels).to(torch.bfloat16) / 8
                mlp = torch.nn.ModuleDict({
                    "router": torch.nn.Linear(channels, experts, dtype=torch.bfloat16),
                    "fc1": torch.nn.ParameterDict({"weight": torch.nn.Parameter(
                        torch.randn(experts, 2 * inner, channels).to(torch.bfloat16) / 8
                    )}),
                    "fc2": torch.nn.ParameterDict({"weight": torch.nn.Parameter(
                        torch.randn(experts, channels, inner).to(torch.bfloat16) / 8
                    )}),
                })
                with torch.inference_mode():
                    actual = layers.moe_mlp(x, mlp, active)
                    flat = x.reshape(-1, channels)
                    logits = mlp.router(flat)
                    top_logits, ids = logits.topk(active, dim=-1)
                    routing = top_logits.float().softmax(-1).to(torch.bfloat16)
                    expected = torch.zeros_like(flat, dtype=torch.float32)
                    for token in range(flat.shape[0]):
                        for route in range(active):
                            expert = int(ids[token, route])
                            expanded = (mlp.fc1.weight[expert].float() @ flat[token].float()).to(torch.bfloat16)
                            gate, up = expanded.chunk(2)
                            hidden = torch.nn.functional.gelu(gate) * (up + 1)
                            result = (mlp.fc2.weight[expert].float() @ hidden.float()).to(torch.bfloat16)
                            expected[token] += (result * routing[token, route]).float()
                    # BF16 reduction order differs between bmm and per-expert
                    # sequential sums; compare to FP32 accumulated reference.
                    torch.testing.assert_close(
                        actual.float().reshape_as(expected), expected,
                        atol=0.001, rtol=0.04,
                    )
        self.assertFalse(torch.cuda.is_initialized())


if __name__ == "__main__":
    unittest.main()
