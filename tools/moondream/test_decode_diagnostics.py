"""CPU checks for isolated, serial segmentation ablations; no model download."""

from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import unittest

import torch
from kestrel.models.moondream.config import TokenizerConfig
from kestrel.models.moondream.skills.segment import SegmentSkill
from kestrel.runtime.tokens import CoordToken, SizeToken, TextToken
from kestrel.scheduler.types import GenerationRequest
from decode_diagnostics import install_decode_diagnostics


class DecodeDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.skill = SegmentSkill()
        self.flags = {}
        self.runtime = SimpleNamespace(
            _cfg=SimpleNamespace(max_batch_size=1, enable_cuda_graphs=False),
            spatial_tables=SimpleNamespace(coord_value_lut=torch.linspace(0, 1, 1024).bfloat16()),
            prompt_template=TokenizerConfig(), eos_token_ids=(0,),
            tokenizer=SimpleNamespace(encode=lambda text: SimpleNamespace(ids=[1234])))
        self.original_lut = self.runtime.spatial_tables.coord_value_lut.clone()
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.close = install_decode_diagnostics(self.flags)

    def tearDown(self):
        self.close()
        self.output.__exit__(None, None, None)

    def prepare(self):
        context = self.skill.build_request(b"unused", {"object": "square"}, None).request_context
        tokens = self.skill.build_prompt_tokens(self.runtime, context)
        request = GenerationRequest(1, "square", tokens, 128, self.skill, context)
        return context, request

    def state(self):
        context, request = self.prepare()
        # Match the executor's keyword call; a tracing wrapper must not be
        # required to adapt this diagnostic to the real skill interface.
        return self.skill.create_state(runtime=self.runtime, request=request, request_context=context)

    def test_baseline_prompt_lut_and_masks_unchanged(self):
        context, request = self.prepare()
        self.assertEqual([token.token_id for token in request.prompt_tokens], [0, 1, 17374, 2, 1234, 3])
        state = self.skill.create_state(runtime=self.runtime, request=request, request_context=context)
        self.assertFalse(state.mask_is_stateful)
        for token in (CoordToken(.4), CoordToken(.5), SizeToken(.1, .2), TextToken(10)):
            self.assertIsNone(state.suppressed_token_ids(self.runtime))
            state.append_token(token)
        torch.testing.assert_close(self.runtime.spatial_tables.coord_value_lut, self.original_lut, rtol=0, atol=0)

    def test_suppression_only_after_three_spatial_tokens_and_case_snapshot(self):
        self.flags["suppress_first_path_eos"] = True
        context, request = self.prepare()
        self.flags.clear()  # The prepared request must retain its own settings.
        state = self.skill.create_state(runtime=self.runtime, request=request, request_context=context)
        self.assertTrue(state.mask_is_stateful)
        for token in (CoordToken(.4), CoordToken(.5), SizeToken(.1, .2)):
            self.assertIsNone(state.suppressed_token_ids(self.runtime))
            state.append_token(token)
        self.assertEqual(state.suppressed_token_ids(self.runtime), [0])
        state.append_token(TextToken(10))
        self.assertIsNone(state.suppressed_token_ids(self.runtime))
        next_state = self.state()
        self.assertFalse(next_state.mask_is_stateful)
        self.assertIsNone(next_state.suppressed_token_ids(self.runtime))

    def test_lut_change_and_reset_between_cases_and_cleanup(self):
        self.flags["coord_denominator_1024"] = True
        self.prepare()
        expected = (torch.arange(1024).float() / 1024).bfloat16()
        torch.testing.assert_close(self.runtime.spatial_tables.coord_value_lut, expected, rtol=0, atol=0)
        self.assertFalse(torch.equal(expected, self.original_lut))
        self.flags.clear()
        self.prepare()
        torch.testing.assert_close(self.runtime.spatial_tables.coord_value_lut, self.original_lut, rtol=0, atol=0)
        self.flags["coord_denominator_1024"] = True
        self.prepare()
        self.close()
        torch.testing.assert_close(self.runtime.spatial_tables.coord_value_lut, self.original_lut, rtol=0, atol=0)

    def test_forced_boundary_only_at_exact_bbox_step_then_restores(self):
        self.flags["force_svg_start_after_bbox"] = True
        state = self.state()
        self.assertTrue(state.mask_is_stateful)
        for token in (CoordToken(.4), CoordToken(.5), SizeToken(.1, .2)):
            self.assertIsNone(state.allowed_token_ids(self.runtime))
            self.assertIsNone(state.suppressed_token_ids(self.runtime))
            state.append_token(token)
        self.assertEqual(state.allowed_token_ids(self.runtime), [10])
        self.assertIsNone(state.suppressed_token_ids(self.runtime))
        state.append_token(TextToken(10))
        self.assertIsNone(state.allowed_token_ids(self.runtime))
        self.assertIsNone(state.suppressed_token_ids(self.runtime))
        self.flags.clear()
        baseline = self.state()
        self.assertFalse(baseline.mask_is_stateful)
        self.assertIsNone(baseline.allowed_token_ids(self.runtime))

    def test_forced_boundary_requires_spatial_prefix_and_rejects_combined_ablation(self):
        self.flags["force_svg_start_after_bbox"] = True
        state = self.state()
        for token in (TextToken(65), TextToken(36), TextToken(36)):
            state.append_token(token)
        self.assertIsNone(state.allowed_token_ids(self.runtime))
        self.flags["suppress_first_path_eos"] = True
        with self.assertRaisesRegex(ValueError, "not both"):
            self.prepare()
        torch.testing.assert_close(self.runtime.spatial_tables.coord_value_lut, self.original_lut, rtol=0, atol=0)


if __name__ == "__main__":
    torch.set_num_threads(1)
    unittest.main()
