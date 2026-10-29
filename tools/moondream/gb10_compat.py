"""Opt-in, provisional Photon MoE adapter for GB10; no vendor files are changed.

This retains the checkpoint's FP8 storage and converts only one routed expert
at a time to BF16. It uses ordinary PyTorch/cuBLAS operations, not Photon's
optimized FP8 MoE kernels. CUDA graphs must be disabled and decode_path must
be ``native``. This is a correctness/compatibility path, not a speed claim.
"""

from collections import defaultdict
from importlib.metadata import version
from types import SimpleNamespace

import torch
import torch.nn.functional as F


def _fp8_view(value):
    if value.dtype == torch.uint8:
        return value.view(torch.float8_e4m3fn)
    if value.dtype != torch.float8_e4m3fn:
        raise ValueError("The GB10 adapter accepts E4M3 FP8 expert weights only")
    return value


def _mm_fp32(x, weight):
    """BF16 storage and products, FP32 accumulation/output on CUDA."""
    if x.is_cuda:
        return torch.mm(x, weight.T, out_dtype=torch.float32)
    # CPU is a small-shape numerical oracle only, never the deployed path.
    return torch.mm(x.float(), weight.float().T)


@torch.no_grad()
def fp8_moe_forward(x, topk_ids, topk_weights, up, down, up_scale,
                    down_scale, *, chunk_tokens=256):
    """MD3 channel-scaled FP8 MoE, with 8-row interleaved gate/up rows.

    The arithmetic is GELU(gate) * (up + 1), followed by each expert's down
    projection and routing probability. No routing renormalization is added.
    The temporary weight footprint is 6*H*I bytes for BF16 up+down weights,
    independent of the total number of experts/layers. There is no weight cache.
    """
    if x.ndim != 2 or x.dtype not in (torch.bfloat16, torch.float32):
        raise ValueError("Expected [tokens, hidden] BF16/FP32 activations")
    if x.is_cuda and x.dtype != torch.bfloat16:
        raise ValueError("The CUDA adapter requires BF16 activations")
    if x.is_cuda and torch.cuda.is_current_stream_capturing():
        raise RuntimeError("GB10 compatibility mode requires enable_cuda_graphs=False")
    if not isinstance(chunk_tokens, int) or chunk_tokens <= 0:
        raise ValueError("chunk_tokens must be positive")
    if up.ndim != 3 or down.ndim != 3:
        raise ValueError("Expert weights must be rank 3")
    experts, rows, hidden = up.shape
    intermediate = rows // 2
    if rows % 2 or intermediate % 8 or down.shape != (experts, hidden, intermediate):
        raise ValueError("Invalid MD3 expert shape or 8-row interleave")
    if x.shape[1] != hidden:
        raise ValueError("Activation hidden dimension does not match weights")
    if up_scale is None or down_scale is None:
        raise ValueError("Both per-output-channel FP8 scales are required")
    if up_scale.shape != (experts, rows) or down_scale.shape != (experts, hidden):
        raise ValueError("Only channel scales are supported")
    if (topk_ids.ndim != 2 or topk_ids.shape[0] != x.shape[0]
            or topk_weights.shape != topk_ids.shape
            or topk_ids.dtype not in (torch.int32, torch.int64)):
        raise ValueError("Routing requires matching [tokens, top_k] IDs and weights")
    values = (topk_ids, topk_weights, up, down, up_scale, down_scale)
    if any(value.device != x.device for value in values):
        raise ValueError("All tensors must be on the same device")
    up_fp8, down_fp8 = _fp8_view(up), _fp8_view(down)
    if not x.shape[0]:
        return torch.empty_like(x)

    # One D2H copy per MoE layer. Sorting on the host makes the bounded path
    # explicit and requires eager execution; this is not capture-compatible.
    routes = defaultdict(list)
    for token, assignments in enumerate(topk_ids.detach().cpu().tolist()):
        for slot, expert in enumerate(assignments):
            if not 0 <= expert < experts:
                raise ValueError("Routing contains an out-of-range expert ID")
            routes[expert].append((token, slot))
    output = torch.zeros(x.shape, dtype=torch.float32, device=x.device)
    for expert, assignments in routes.items():
        # FP8 values are exactly representable in BF16. Apply channel scales
        # after the FP32 dot product, avoiding an extra BF16 weight rounding.
        up_weight = up_fp8[expert].to(dtype=x.dtype)
        down_weight = down_fp8[expert].to(dtype=x.dtype)
        for start in range(0, len(assignments), chunk_tokens):
            batch = assignments[start:start + chunk_tokens]
            token_ids = torch.tensor([p[0] for p in batch], device=x.device)
            slot_ids = torch.tensor([p[1] for p in batch], device=x.device)
            inputs = x.index_select(0, token_ids)
            projected = (_mm_fp32(inputs, up_weight)
                         * up_scale[expert].float()).to(x.dtype)
            pairs = projected.reshape(-1, intermediate // 8, 2, 8)
            gate = pairs[:, :, 0, :].reshape(-1, intermediate).float()
            residual = pairs[:, :, 1, :].reshape(-1, intermediate).float()
            activated = (F.gelu(gate, approximate="none")
                         * (residual + 1)).to(x.dtype)
            contribution = _mm_fp32(activated, down_weight)
            contribution.mul_(down_scale[expert].float())
            contribution.mul_(topk_weights[token_ids, slot_ids].float()[:, None])
            output.index_add_(0, token_ids, contribution)
        # Do not retain the previous expert while allocating the next one.
        del up_weight, down_weight
    return output.to(x.dtype)


class GB10TorchMoeRuntime:
    """Implements Kestrel's existing per-layer ``_moe_runtime`` extension seam."""

    def prepare(self, spec, capacity, *, device):
        device = torch.device(device)
        if device.type != "cuda" or torch.cuda.get_device_capability(device) != (12, 1):
            raise ValueError("This opt-in adapter is limited to a real GB10/SM121 GPU")
        if spec.weight_format != "fp8_e4m3" or spec.activation != "gelu":
            raise ValueError("Adapter supports MD3 FP8 residual-GELU experts only")
        if capacity.max_loras or capacity.max_lora_rank:
            raise NotImplementedError("GB10 compatibility mode does not support LoRA")
        return SimpleNamespace(spec=spec, capacity=capacity, device=device)

    def forward(self, handle, *, x, topk_ids, topk_weights, weights,
                out=None, lora=None, base_up_out=None):
        if lora is not None or base_up_out is not None:
            raise NotImplementedError("GB10 compatibility mode does not support LoRA")
        if weights.weight_scale_layout != "channel":
            raise ValueError("Adapter requires interleaved per-channel FP8 weights")
        if topk_ids.shape != (x.shape[0], handle.spec.top_k):
            raise ValueError("Routing shape does not match the prepared MoE spec")
        result = fp8_moe_forward(x, topk_ids, topk_weights, weights.up, weights.down,
                                 weights.up_scale, weights.down_scale)
        if out is not None:
            if out.shape != result.shape or out.dtype != result.dtype:
                raise ValueError("Invalid MoE output buffer")
            out.copy_(result)
            return out
        return result


def install_gb10_compat():
    """Call once, before md.photon; installs only in this Python process.

    The original Kestrel constructor/forward and public weight-packing API
    remain in use. New MoE layers receive an application-owned runtime object.
    No GPU identity is overridden and no installed package is written.
    """
    expected = {'moondream': '2.6.1', 'kestrel': '0.9.1',
                'kestrel-kernels': '0.7.4', 'torch': '2.13.0'}
    mismatches = {name: version(name) for name, pinned in expected.items()
                  if version(name) != pinned}
    if mismatches:
        raise RuntimeError(f"Unqualified Photon adapter package versions: {mismatches}")
    from kestrel.models.moondream.moe import MoEModule

    if torch.cuda.get_device_capability() != (12, 1):
        raise ValueError("GB10 compatibility mode requires actual SM121 hardware")
    if not getattr(MoEModule.__init__, "_gb10_torch_adapter", False):
        original_init = MoEModule.__init__

        def initialize(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self._moe_runtime = GB10TorchMoeRuntime()

        initialize._gb10_torch_adapter = True
        MoEModule.__init__ = initialize
    return {"moe_backend": "gb10_torch_compat", "optimized_fp8_moe": False,
            "enable_cuda_graphs": False, "decode_path": "native",
            "weight_storage": "fp8", "expert_compute": "bf16_with_fp32_accumulation"}
