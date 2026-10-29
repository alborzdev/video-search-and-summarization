"""CPU protocol checks; no checkpoints, network, Photon or GPU needed."""

import sys
from types import ModuleType, SimpleNamespace
import unittest

import torch

from reference_decode import _prompt_ids, _svg_path, segment


class Tokenizer:
    words = {65: "M", 64: "L", 55: "C", 78: "Z", 33: "-",
             100: "0", 101: "960", 102: "39", 103: "person",
             0: "<EOS>", 10: "<SVG>", 11: "</SVG>"}

    def encode(self, value):
        return SimpleNamespace(ids=[103] if value == "person" else [104])

    def decode(self, ids, skip_special_tokens=True):
        return "".join(self.words.get(i, f"<{i}>") for i in ids
                       if not skip_special_tokens or i > 20)


_FAKE = ModuleType("_reference_decode_cpu_fixture")


def _decode_coordinate(hidden, region):
    logits = torch.full((1, 1, 1024), -20.0)
    logits[..., 512] = 20.0
    return logits


def _decode_size(hidden, region):
    logits = torch.full((2, 1024), -20.0)
    logits[..., 921] = 20.0
    return logits


_FAKE.decode_coordinate = _decode_coordinate
_FAKE.decode_size = _decode_size
_FAKE.encode_coordinate = lambda value, region: torch.zeros(1, 4)
_FAKE.encode_size = lambda value, region: torch.zeros(4)
_FAKE.text_encoder = lambda value, text: torch.zeros(1, 1, 4)
sys.modules[_FAKE.__name__] = _FAKE


class Model:
    __module__ = _FAKE.__name__

    def __init__(self, sequence):
        self.sequence = sequence
        self.device = torch.device("cpu")
        self.config = SimpleNamespace(text=SimpleNamespace(max_context=1024))
        self.tokenizer = Tokenizer()
        self.region = self.text = None
        self.calls = []

    def _logits(self, step):
        logits = torch.full((1, 200), -20.0)
        logits[0, self.sequence[step]] = 4.0
        if step == 3:
            logits[0, 10] = 1.0
        return logits

    def encode_image(self, image):
        return SimpleNamespace(pos=730)

    def load_encoded_image(self, image):
        self.step = 0

    def _prefill_prompt(self, prompt, pos, **kwargs):
        self.prompt, self.prefill_kwargs = prompt.tolist()[0], kwargs
        return self._logits(0), torch.zeros(1, 2, 4), None, pos + prompt.shape[1]

    def _decode_one_tok(self, emb, mask, pos_ids, lora, lm_head_indices):
        assert lm_head_indices is None
        assert tuple(emb.shape) == (1, 1, 4)
        assert mask[0, 0, pos_ids[0]]
        self.calls.append(int(pos_ids[0]))
        self.step += 1
        return self._logits(self.step), torch.zeros(1, 1, 4)


class ProtocolTests(unittest.TestCase):
    def test_prompt_inserts_spatial_refs_without_second_bos(self):
        ids, refs = _prompt_ids(Tokenizer(), "person", [[.5, .5], [.1, .2, .4, .6]])
        self.assertEqual(ids, [1, 17374, 2, 5, 5, 5, 5, 6, 103, 3])
        self.assertEqual(len(refs), 2)

    def test_invalid_reference_rejected(self):
        with self.assertRaises(ValueError):
            _prompt_ids(Tokenizer(), "person", [[.6, .5, .2, .9]])

    def test_svg_decodes_integer_tokens_and_minus(self):
        path, _ = _svg_path(Tokenizer(), [5, 5, 6, 10, 65, 33, 102, 100,
                                        64, 101, 100, 64, 100, 101, 78, 11, 0])
        self.assertEqual(path, "M -0.040625 0 L 1 0 L 0 1 Z")

    def test_partial_svg_is_not_accepted(self):
        with self.assertRaises(ValueError):
            _svg_path(Tokenizer(), [65, 100])

    def test_baseline_preserves_eos_after_box(self):
        model = Model([5, 5, 6, 0])
        result = segment(model, None, "person")
        self.assertEqual(result["token_ids"], [5, 5, 6, 0])
        self.assertEqual(result["finish_reason"], "eos")
        self.assertEqual(result["path"], "")
        self.assertFalse(result["forced_boundary"])
        self.assertGreater(result["post_bbox"]["eos_probability"], .9)
        self.assertEqual(model.calls, [735, 736, 737])

    def test_explicit_conditioning_retains_unmodified_probability(self):
        model = Model([5, 5, 6, 0, 65, 100, 100, 64, 101, 100,
                       64, 100, 101, 78, 11, 0])
        result = segment(model, None, "person", spatial_refs=[[.5, .5]], condition_svg=True)
        self.assertEqual(result["path"], "M 0 0 L 1 0 L 0 1 Z")
        self.assertEqual(result["finish_reason"], "eos")
        self.assertEqual(sum(t["forced"] for t in result["raw_tokens"]), 1)
        self.assertEqual(result["post_bbox"]["greedy_token_id"], 0)
        self.assertGreater(result["post_bbox"]["eos_probability"], .9)
        self.assertEqual(model.prefill_kwargs["spatial_refs"], [(0.5, 0.5)])

    def test_token_budget_bounds_decoder(self):
        model = Model([5, 5, 6, 0])
        result = segment(model, None, "person", max_tokens=2)
        self.assertEqual(result["token_ids"], [5, 5])
        self.assertEqual(result["finish_reason"], "max_tokens")
        self.assertIsNone(result["bbox"])


if __name__ == "__main__":
    unittest.main()
