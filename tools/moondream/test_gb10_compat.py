"""CPU-only numerical checks; no CUDA context, model loading, or services."""
import unittest

import torch
import torch.nn.functional as F

from gb10_compat import fp8_moe_forward


def interleave(value, intermediate):
    # Explicit row list, independent of the adapter's reshape/unpack logic.
    order = [row for start in range(0, intermediate, 8)
             for row in (*range(start, start + 8),
                         *range(intermediate + start, intermediate + start + 8))]
    return value[:, order].contiguous()


def oracle(x, ids, routing, up, down, up_scales, down_scales):
    """Slow per-token reference using original contiguous gate/up halves."""
    result = torch.zeros_like(x, dtype=torch.float32)
    intermediate = down.shape[2]
    for token in range(x.shape[0]):
        for slot in range(ids.shape[1]):
            expert = ids[token, slot].item()
            # The reference dequantizes weights before GEMM rather than using
            # the adapter's post-GEMM scale epilogue.
            wu = up[expert].float() * up_scales[expert, :, None]
            wd = down[expert].float() * down_scales[expert, :, None]
            projected = F.linear(x[token].float(), wu).to(x.dtype).float()
            active = (F.gelu(projected[:intermediate], approximate="none")
                      * (projected[intermediate:] + 1)).to(x.dtype).float()
            result[token] += F.linear(active, wd) * routing[token, slot]
    return result.to(x.dtype)


class CompatibilityMathTests(unittest.TestCase):
    def fixtures(self, tokens=7, experts=5, hidden=12, intermediate=16, top_k=3,
                 dtype=torch.float32):
        generator = torch.Generator().manual_seed(42)
        x = torch.randn(tokens, hidden, generator=generator).to(dtype)
        up = (torch.randn(experts, 2 * intermediate, hidden,
                          generator=generator) / 3).to(torch.float8_e4m3fn)
        down = (torch.randn(experts, hidden, intermediate,
                            generator=generator) / 3).to(torch.float8_e4m3fn)
        up_scale = torch.rand(experts, 2 * intermediate, generator=generator) + .1
        down_scale = torch.rand(experts, hidden, generator=generator) + .1
        # Duplicated expert assignments deliberately test weighted accumulation.
        ids = torch.randint(experts, (tokens, top_k), generator=generator)
        weights = torch.rand(tokens, top_k, generator=generator)
        return x, ids, weights, up, down, up_scale, down_scale

    def run_case(self, **kwargs):
        x, ids, weights, up, down, us, ds = args = self.fixtures(**kwargs)
        reference = oracle(*args)
        actual = fp8_moe_forward(x, ids, weights,
                                interleave(up.view(torch.uint8), down.shape[2]),
                                down.view(torch.uint8), interleave(us, down.shape[2]),
                                ds, chunk_tokens=2)
        return actual, reference

    def test_interleave_scales_routing_and_chunking_match_float32_oracle(self):
        for dims in [(1, 3, 8, 8, 2), (7, 5, 12, 16, 3), (9, 7, 32, 24, 4)]:
            with self.subTest(dims=dims):
                actual, expected = self.run_case(**dict(zip(
                    ('tokens', 'experts', 'hidden', 'intermediate', 'top_k'), dims)))
                torch.testing.assert_close(actual, expected, rtol=2e-5, atol=3e-6)

    def test_bfloat16_activation_rounding_matches_reference(self):
        actual, expected = self.run_case(dtype=torch.bfloat16)
        torch.testing.assert_close(actual.float(), expected.float(), rtol=.02, atol=.015)
        relative_error = (actual.float() - expected.float()).norm() / expected.float().norm()
        self.assertLess(relative_error.item(), .006)

    def test_residual_plus_one_is_preserved(self):
        # Gate=1 and up=0 must produce a positive output. Standard GEGLU
        # without the residual +1 would return zero and fail this check.
        x = torch.ones(1, 8)
        up = torch.cat((torch.ones(1, 8, 8) / 8, torch.zeros(1, 8, 8)), 1)
        up = up.to(torch.float8_e4m3fn)
        down = torch.ones(1, 8, 8).to(torch.float8_e4m3fn)
        result = fp8_moe_forward(x, torch.zeros(1, 1, dtype=torch.long),
                                torch.ones(1, 1), interleave(up.view(torch.uint8), 8),
                                down, torch.ones(1, 16), torch.ones(1, 8))
        torch.testing.assert_close(result, torch.full_like(x, 8 * F.gelu(torch.tensor(1.)).item()))

    def test_nonunit_routing_weights_are_not_renormalized(self):
        args = list(self.fixtures())
        args[3] = interleave(args[3].view(torch.uint8), args[4].shape[2])
        args[5] = interleave(args[5], args[4].shape[2])
        original = fp8_moe_forward(*args)
        args[2] = args[2] * 3
        torch.testing.assert_close(fp8_moe_forward(*args), original * 3,
                                   rtol=1e-5, atol=2e-6)

    def test_empty_input(self):
        args = list(self.fixtures(tokens=0))
        self.assertEqual(fp8_moe_forward(*args).shape, (0, 12))

    def test_invalid_expert_is_rejected(self):
        args = list(self.fixtures())
        args[1][0, 0] = 100
        with self.assertRaisesRegex(ValueError, 'out-of-range'):
            fp8_moe_forward(*args)

    def test_block_scales_are_rejected(self):
        args = list(self.fixtures())
        args[5] = torch.ones(5, 1, 1)
        with self.assertRaisesRegex(ValueError, 'channel scales'):
            fp8_moe_forward(*args)


if __name__ == '__main__':
    torch.set_num_threads(1)
    unittest.main()
