"""Unsupported, process-only ablations for a serial Photon segmentation probe.

These deliberately alter generation. They are diagnostic experiments, not model
support fixes or deployment settings. Install before Photon construction, after
any prompt experiment and before observational tracing. The shared case mapping
must change only between completed requests, with max_batch_size=1 and no graphs.
"""

from functools import wraps
from importlib.metadata import version
import json
from types import MethodType

import torch


_installed = False


def install_decode_diagnostics(diagnostic_case: dict):
    """Install hooks controlled by boolean flags in ``diagnostic_case``.

    ``coord_denominator_1024`` uses the HF coordinate-bin denominator, preserving
    the LUT dtype. ``suppress_first_path_eos`` suppresses only EOS0 at exactly
    three committed tokens, and only if those tokens form Coord/Coord/Size.
    ``force_svg_start_after_bbox`` instead allows only observed boundary ID10
    at that same step. Its SVG-start meaning is inferred from a generated
    10/path/11 sequence, not an official token-ID contract. The two sampling
    ablations cannot be combined. Neither inserts or constructs path geometry.
    Returns a cleanup callable; use after all requests and remove outer tracing
    first. Normal cases restore the original LUT and preserve original behavior.
    """
    global _installed
    if _installed:
        raise RuntimeError("Decode diagnostics already installed in this process")
    if version("kestrel") != "0.9.1":
        raise RuntimeError("Decode diagnostics were audited only for kestrel==0.9.1")
    if not isinstance(diagnostic_case, dict):
        raise TypeError("diagnostic_case must be the shared per-case dict")
    from kestrel.models.moondream.skills.segment import SegmentSkill
    from kestrel.runtime.tokens import CoordToken, SizeToken

    original_prompt = SegmentSkill.build_prompt_tokens
    original_create = SegmentSkill.create_state
    saved_luts = {}
    settings_by_context = {}

    @wraps(original_prompt)
    def prompt(skill, runtime, context):
        cfg = runtime._cfg
        if cfg.max_batch_size != 1 or cfg.enable_cuda_graphs:
            raise RuntimeError("Decode diagnostics require batch size1 and disabled CUDA graphs")
        flags = {key: bool(diagnostic_case.get(key, False)) for key in
                 ("coord_denominator_1024", "suppress_first_path_eos",
                  "force_svg_start_after_bbox")}
        if flags["suppress_first_path_eos"] and flags["force_svg_start_after_bbox"]:
            raise ValueError("Choose either EOS suppression or SVG-start forcing, not both")
        lut = runtime.spatial_tables.coord_value_lut
        if lut.ndim != 1 or lut.numel() != 1024:
            raise ValueError("This diagnostic requires the audited 1024-bin coordinate LUT")
        key = id(runtime)
        with torch.inference_mode():
            if key not in saved_luts:
                saved_luts[key] = (lut, lut.detach().clone())
            original = saved_luts[key][1]
            # Always reset first: one altered case must not leak into the next.
            lut.copy_(original)
            if flags["coord_denominator_1024"]:
                lut.copy_((torch.arange(1024, device=lut.device, dtype=torch.float32)
                           / 1024).to(dtype=lut.dtype))
            # Prompt admission and decoding may use different CUDA streams.
            # This tiny diagnostic mutation must complete before admission.
            if lut.is_cuda:
                torch.cuda.current_stream(lut.device).synchronize()
        settings_by_context[id(context)] = flags
        print(json.dumps({"stage": "diagnostic_decode_case", "context_id": id(context),
                          **flags, "altered_generation": any(flags.values()),
                          "deployment_supported": False}), flush=True)
        return original_prompt(skill, runtime, context)

    @wraps(original_create)
    def create(skill, runtime, request, request_context):
        context = request_context
        flags = settings_by_context.pop(id(context), None)
        if flags is None:
            raise RuntimeError("Diagnostic state was created without its prepared prompt")
        state = original_create(skill, runtime, request, context)
        if not (flags["suppress_first_path_eos"] or flags["force_svg_start_after_bbox"]):
            return state
        if tuple(runtime.eos_token_ids) != (0,):
            raise ValueError("EOS suppression was audited only for Moondream EOS0")
        state.mask_is_stateful = True
        def after_bbox(self):
            return (self.token_count == 3
                    and isinstance(self.tokens[0], CoordToken)
                    and isinstance(self.tokens[1], CoordToken)
                    and isinstance(self.tokens[2], SizeToken))

        if flags["suppress_first_path_eos"]:
            original_suppression = state.suppressed_token_ids

            def suppressed(self, current_runtime):
                baseline = original_suppression(current_runtime)
                if after_bbox(self):
                    return list(dict.fromkeys([*(baseline or []), 0]))
                return baseline

            state.suppressed_token_ids = MethodType(suppressed, state)
            print(json.dumps({"stage": "diagnostic_eos_suppression_installed",
                              "request_id": request.request_id,
                              "only_at_committed_token_count": 3,
                              "required_prefix": ["coord", "coord", "size"],
                              "suppressed_ids": [0], "deployment_supported": False}), flush=True)
        else:
            original_allowed = state.allowed_token_ids

            def allowed(self, current_runtime):
                baseline = original_allowed(current_runtime)
                if after_bbox(self):
                    if baseline is not None and 10 not in baseline:
                        raise ValueError("Existing skill constraint conflicts with diagnostic boundary ID10")
                    return [10]
                return baseline

            state.allowed_token_ids = MethodType(allowed, state)
            print(json.dumps({"stage": "diagnostic_svg_start_installed",
                              "request_id": request.request_id,
                              "only_at_committed_token_count": 3,
                              "required_prefix": ["coord", "coord", "size"],
                              "allowed_ids": [10],
                              "token_semantics": "SVG-start inferred from observed 10/path/11 sequence",
                              "deployment_supported": False}), flush=True)
        return state

    SegmentSkill.build_prompt_tokens = prompt
    SegmentSkill.create_state = create
    _installed = True

    def close():
        global _installed
        if SegmentSkill.build_prompt_tokens is prompt:
            SegmentSkill.build_prompt_tokens = original_prompt
        if SegmentSkill.create_state is create:
            SegmentSkill.create_state = original_create
        with torch.inference_mode():
            for lut, original in saved_luts.values():
                lut.copy_(original)
                if lut.is_cuda:
                    torch.cuda.current_stream(lut.device).synchronize()
        saved_luts.clear()
        settings_by_context.clear()
        _installed = False

    return close
