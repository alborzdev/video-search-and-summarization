"""Opt-in, process-local observation of Kestrel 0.9.1 segmentation.

Call ``handle = install_trace(out_path)`` before constructing Photon. The JSONL
records exact prompt and generated tokens, sampled-token logits, stop predicates,
and the unmodified decoder result. ``handle.close()`` restores the methods; call
it only after Photon has shut down. No vendor files or model outputs are changed.

Logit observation copies one vocabulary row to CPU and synchronizes the current
stream. A traced run is a correctness diagnostic, never a latency benchmark.
Only segmentation requests are observed. Images and model weights are not saved.
"""

from __future__ import annotations

import functools
import hashlib
from importlib.metadata import PackageNotFoundError, version
import inspect
import json
import math
from pathlib import Path
import sys
import threading
import time


_active = None


def _number(value):
    value = float(value)
    return value if math.isfinite(value) else str(value)


class TraceHandle:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("x", encoding="utf-8")
        self._lock = threading.Lock()
        self._patches = []
        self._sample_counts = {}
        self._candidates = {}
        self._failed = False

    def write(self, event, **data):
        # Observation failures must not turn a valid inference into a failure.
        try:
            with self._lock:
                self._file.write(json.dumps(
                    {"event": event, "monotonic_s": time.monotonic(), **data},
                    ensure_ascii=False, allow_nan=False) + "\n")
                self._file.flush()
        except Exception as exc:
            if not self._failed:
                self._failed = True
                print(f"Segmentation trace write failed: {exc!r}", file=sys.stderr)

    def observe(self, callback):
        try:
            callback()
        except Exception as exc:
            self.write("trace_error", error=repr(exc))

    def patch(self, cls, name, wrapper):
        original = getattr(cls, name)
        replacement = functools.wraps(original)(wrapper(original))
        setattr(cls, name, replacement)
        self._patches.append((cls, name, original, replacement))

    def close(self):
        global _active
        if self._file.closed:
            return
        for cls, name, original, replacement in reversed(self._patches):
            if getattr(cls, name) is replacement:
                setattr(cls, name, original)
        self.write("trace_closed")
        self._file.close()
        if _active is self:
            _active = None

    @staticmethod
    def token(runtime, token):
        from kestrel.runtime.tokens import CoordToken, SizeToken, TextToken
        if isinstance(token, TextToken):
            return {"kind": "text", "id": int(token.token_id),
                    "vocabulary_text": runtime.tokenizer.id_to_token(token.token_id),
                    "decoded": runtime.tokenizer.decode([token.token_id], skip_special_tokens=False)}
        if isinstance(token, CoordToken):
            return {"kind": "coord", "id": int(runtime.config.tokenizer.coord_id),
                    "value": _number(token.pos)}
        if isinstance(token, SizeToken):
            return {"kind": "size", "id": int(runtime.config.tokenizer.size_id),
                    "width": _number(token.width), "height": _number(token.height)}
        return {"kind": type(token).__name__, "repr": repr(token)}

    def prompt(self, runtime, context, tokens):
        from kestrel.runtime.tokens import TextToken
        template = runtime.prompt_template.segment()
        ids = [int(token.token_id) for token in tokens if isinstance(token, TextToken)]
        self.write(
            "prompt", context_id=id(context), model=runtime.model_name,
            object=context.object, spatial_refs=context.spatial_refs,
            tokens=[self.token(runtime, token) for token in tokens], text_token_ids=ids,
            decoded_text=runtime.tokenizer.decode(ids, skip_special_tokens=False),
            template_prefix=list(template.prefix) if template else None,
            template_suffix=list(template.suffix) if template else None,
            bos_id=int(runtime.prompt_template.bos_id),
            eos_ids=list(runtime.eos_token_ids),
            note="Image embeddings are inserted by the runtime; these are the exact skill prompt tokens.")

    def sample(self, scheduler, logits, sequences, result, *, sampler_path="generic"):
        import torch
        from kestrel.models.moondream.skills.segment import SegmentSkillState
        runtime = scheduler.runtime
        for row_index, seq in enumerate(sequences):
            if not isinstance(seq.skill_state, SegmentSkillState) or seq.request is None:
                continue
            request_id = seq.request.request_id
            sample_index = self._sample_counts.get(request_id, 0)
            self._sample_counts[request_id] = sample_index + 1
            # Copy after the original sampler returns: it has applied all masks.
            # Every numerical operation below is on the copy, never live logits.
            row = logits[row_index].detach().to(device="cpu", dtype=torch.float32)
            sampled_id = int(result[0][row_index].detach().cpu().item())
            key = id(runtime.tokenizer)
            if key not in self._candidates:
                candidates = {i: "reserved_token" for i in range(21)}
                for command in ("M", " M", "L", " L", "C", " C", "Z", " Z"):
                    for token_id in runtime.tokenizer.encode(command).ids:
                        candidates[token_id] = f"SVG command spelling: {command!r}"
                # Tokenizer may use reserved IDs for SVG boundaries. Record all
                # reserved IDs above; do not invent a mapping from paper labels.
                self._candidates[key] = candidates
            candidates = self._candidates[key]
            top_ids = torch.topk(row, min(10, row.numel())).indices.tolist()
            selected_ids = sorted(set(top_ids + list(candidates)
                                      + list(scheduler._eos_token_ids) + [sampled_id]))
            normalizer = torch.logsumexp(row, dim=0).item()
            token_stats = []
            for token_id in selected_ids:
                if not 0 <= token_id < row.numel():
                    continue
                value = row[token_id].item()
                token_stats.append({
                    "id": token_id, "vocabulary_text": runtime.tokenizer.id_to_token(token_id),
                    "logit": _number(value), "rank": int((row > value).sum().item()) + 1,
                    "softmax_probability": _number(math.exp(value - normalizer))
                    if math.isfinite(normalizer) else None,
                    "candidate": candidates.get(token_id),
                })
            self.write(
                "sample", request_id=request_id, context_id=id(seq.request.request_context),
                sample_index=sample_index, committed_token_count=seq.skill_state.token_count,
                sampled_id=sampled_id, eos_ids=sorted(scheduler._eos_token_ids),
                temperature=seq.request.temperature, top_p=seq.request.top_p,
                top_token_ids=top_ids, token_stats=token_stats,
                nonfinite_logits=int((~torch.isfinite(row)).sum().item()),
                logits_stage="after_original_sampler_masks",
                sampler_path=sampler_path,
                probability_note="Unscaled softmax of observed logits; not a calibrated confidence.")


def install_trace(out_path):
    """Install observational hooks and return a closeable TraceHandle.

    The destination must not exist. Unknown Kestrel versions fail before any
    hooks are installed. Installation does not create a CUDA context.
    """
    global _active
    if _active is not None:
        raise RuntimeError("A segmentation trace is already installed in this process")
    if version("kestrel") != "0.9.1":
        raise RuntimeError("Segmentation trace was audited only for kestrel==0.9.1")
    from kestrel.models.moondream.skills.segment import SegmentSkill, SegmentSkillState
    from kestrel.runtime.tokens import TextToken
    from kestrel.scheduler.scheduler import GenerationScheduler

    handle = TraceHandle(out_path)
    versions = {}
    for package in ("moondream", "kestrel", "kestrel-kernels", "kestrel-native", "torch"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    methods = [(SegmentSkill, "build_prompt_tokens"), (SegmentSkill, "create_state"),
               (SegmentSkillState, "consume_step"), (SegmentSkillState, "finalize"),
               (GenerationScheduler, "_sample_batch"),
               (GenerationScheduler, "_finalize_sampling_on_stream"),
               (GenerationScheduler, "_mark_finished_if_needed")]
    hashes = {f"{cls.__name__}.{name}": hashlib.sha256(
        inspect.getsource(getattr(cls, name)).encode()).hexdigest() for cls, name in methods}
    handle.write("trace_installed", versions=versions, source_sha256=hashes,
                 observation_only=True, performance_measurement_valid=False)

    def prompt_wrapper(original):
        def wrapped(self, runtime, request_context):
            try:
                result = original(self, runtime, request_context)
            except Exception as exc:
                handle.write("prompt_error", context_id=id(request_context), error=repr(exc))
                raise
            handle.observe(lambda: handle.prompt(runtime, request_context, result))
            return result
        return wrapped

    def state_wrapper(original):
        def wrapped(self, runtime, request, request_context):
            result = original(self, runtime, request, request_context)
            handle.observe(lambda: handle.write(
                "request", request_id=request.request_id, context_id=id(request_context),
                max_new_tokens=request.max_new_tokens, temperature=request.temperature,
                top_p=request.top_p, prompt_length=request.prompt_length,
                image_length=request.image_length,
                generated_prefix_length=request.generated_prefix_length,
                allowed_token_ids=result.allowed_token_ids(runtime),
                suppressed_token_ids=result.suppressed_token_ids(runtime),
                skill_stop_token_ids=result.stop_token_ids(runtime),
                runtime_eos_ids=list(runtime.eos_token_ids)))
            return result
        return wrapped

    def consume_wrapper(original):
        def wrapped(self, runtime, step):
            result = original(self, runtime, step)
            handle.observe(lambda: handle.write(
                "consume", request_id=self.request.request_id if self.request else None,
                context_id=id(self._request), position=step.position, phase=step.phase,
                logprob=step.logprob, token=handle.token(runtime, step.token),
                token_count=self.token_count))
            return result
        return wrapped

    def finalize_wrapper(original):
        def wrapped(self, runtime, *, reason):
            try:
                result = original(self, runtime, reason=reason)
            except Exception as exc:
                handle.write("finalize_error", context_id=id(self._request),
                             reason=reason, error=repr(exc))
                raise
            handle.observe(lambda: handle.write(
                "finalize", request_id=self.request.request_id if self.request else None,
                context_id=id(self._request), reason=reason, output=result.output,
                tokens=[handle.token(runtime, token) for token in result.tokens]))
            return result
        return wrapped

    def sample_wrapper(original):
        def wrapped(self, logits, sequences, out, **kwargs):
            result = original(self, logits, sequences, out, **kwargs)
            handle.observe(lambda: handle.sample(self, logits, sequences, result))
            return result
        return wrapped

    def finalize_sampling_wrapper(original):
        trace_handle = handle
        def wrapped(self, handle, plan=None):
            result = original(self, handle, plan)
            def record():
                # The fused all-greedy decode path bypasses _sample_batch.
                # Generic sampling was already observed by the other hook.
                if self._can_publish_greedy_tail(plan):
                    slot = self.runtime.decode_slots[handle.slot_id]
                    count = len(handle.sequences)
                    trace_handle.sample(
                        self, slot.logits[:count], handle.sequences,
                        (slot.sampled_ids[:count],), sampler_path="fused_greedy_tail")
            trace_handle.observe(record)
            return result
        return wrapped

    def stop_wrapper(original):
        def wrapped(self, seq):
            def record():
                if not isinstance(seq.skill_state, SegmentSkillState):
                    return
                token = seq.last_token
                text_id = token.token_id if isinstance(token, TextToken) else None
                skill_stops = seq.skill_state.stop_token_ids(self.runtime)
                handle.write(
                    "stop_check", request_id=seq.request.request_id,
                    context_id=id(seq.request.request_context),
                    last_token=handle.token(self.runtime, token),
                    model_eos_hit=text_id in self._eos_token_ids if text_id is not None else False,
                    skill_stop_hit=text_id in skill_stops if text_id is not None and skill_stops else False,
                    max_new_hit=seq.skill_state.token_count >= seq.request.max_new_tokens,
                    max_context_hit=seq.total_length >= seq.state.max_length,
                    generated_count=seq.skill_state.token_count,
                    max_new_tokens=seq.request.max_new_tokens,
                    total_length=seq.total_length, max_context_length=seq.state.max_length,
                    scheduler_eos_ids=sorted(self._eos_token_ids))
            handle.observe(record)
            return original(self, seq)
        return wrapped

    for (cls, name), factory in zip(methods, (prompt_wrapper, state_wrapper, consume_wrapper,
                                            finalize_wrapper, sample_wrapper,
                                            finalize_sampling_wrapper, stop_wrapper)):
        handle.patch(cls, name, factory)
    _active = handle
    return handle
