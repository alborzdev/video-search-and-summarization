"""Load the pinned official Preview PyTorch model without Photon or new weights.

The FP8 checkpoint is read-only mmap on CPU. Expert weights are dequantized
as FP32(weight) * FP32(channel_scale), rounded once to BF16, and copied one
expert at a time. The official model's forward functions remain unchanged.
Imports are lazy so the caller can configure CUDA visibility and library paths.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import replace
from pathlib import Path
import sys
import time
import types


PREVIEW_REVISION = "5112966d1a723413b1c9a1e8bea272b72e647b35"
STARMIE_SHA256 = "0512fdcac4a5f9e7746cbefce4a468dc93bf0f93f11e701b84f8b31bff199e9c"
_SOURCE_SHA256 = {
    "config.py": "56e47be6abd46b77b73efd2b87d622e8cd5c3c4a87cce4d564c15598cf7ed8c2",
    "image_crops.py": "1f3f469fcbd3291966c6f9fda5c90f8044d39b391261bac14ef6bbcfb76496cb",
    "layers.py": "56e3d4dbb74414d2894a0724ce3ac316b9cbbd20748738aefe4d2ac093422ab1",
    "lora.py": "b9bd0121a6e1fc525bf06e43f56ff83ff22c2ff68b44fe55e1e0ec4232032d54",
    "moondream.py": "33263b4260ca39d0569996b1b83a4a3c92ab08075dee497799a858a07af4fd1e",
    "region.py": "1940048c322247275fdcf45cf210d43a1dd710f2985eb82c49855dba72321b2f",
    "rope.py": "e8327c01c268564e8d262a8d7347a0da4463167754733f7eb0a50ab5eb141b00",
    "text.py": "22968acd8812bdfa23f480b7476f7acf5758c56d5b5776edd876270f7b577d48",
    "utils.py": "08d33430923d83ad26dfdbbc58d6df0f363a4c3c05cbfd8018f6e2c98c82ed59",
    "vision.py": "f524cd4227df0394b0b1e73f281c93791267849729fc13a874a9071fff6f1eed",
}


def _available_bytes() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("Cannot read MemAvailable for the unified-memory guard")


def _require_headroom(reserve_bytes: int, additional_bytes: int = 0) -> int:
    available = _available_bytes()
    if available < reserve_bytes + additional_bytes:
        raise RuntimeError(
            "Insufficient unified-memory headroom: "
            f"available={available}, reserve={reserve_bytes}, "
            f"additional={additional_bytes} bytes"
        )
    return available


def _import_reference(source_dir: Path):
    hashes = {}
    for name, expected_hash in _SOURCE_SHA256.items():
        path = source_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if hashes[name] != expected_hash:
            raise ValueError(f"Source differs from audited Preview revision {PREVIEW_REVISION}: {name}")
    package_name = "_moondream_preview_reference_" + hashlib.sha256(
        str(source_dir.resolve()).encode()
    ).hexdigest()[:12]
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(source_dir)]
        package.__package__ = package_name
        sys.modules[package_name] = package
    return (
        importlib.import_module(package_name + ".moondream"),
        importlib.import_module(package_name + ".config"),
        hashes,
    )


def _mapping(config):
    """Return destination -> (source, optional scale, optional transpose)."""
    mapping = {}

    def add(dst, src, scale=None, transpose=False):
        if dst in mapping:
            raise ValueError(f"Duplicate destination: {dst}")
        mapping[dst] = (src, scale, transpose)

    def linear(dst, src):
        for kind in ("weight", "bias"):
            add(f"{dst}.{kind}", f"{src}.{kind}")

    add("text.wte", "text_model.transformer.embd.wte.weight")
    linear("text.post_ln", "text_model.lm_head.ln")
    linear("text.lm_head", "text_model.lm_head.linear")
    for i in range(config.text.n_layers):
        dst = f"text.blocks.{i}"
        src = f"text_model.transformer.h.{i}"
        linear(dst + ".ln", src + ".ln")
        linear(dst + ".attn.qkv", src + ".mixer.Wqkv")
        linear(dst + ".attn.proj", src + ".mixer.out_proj")
        for kind in ("wq", "wv", "alpha"):
            add(dst + ".attn.tau." + kind, src + ".tau_" + kind)
        if config.text.moe is not None and i >= config.text.moe.start_layer:
            linear(dst + ".mlp.router", src + ".gate")
            add(dst + ".mlp.fc1.weight", src + ".mlp.experts.weight",
                src + ".moe_quant.up_scale")
            add(dst + ".mlp.fc2.weight", src + ".mlp.output_experts.weight",
                src + ".moe_quant.down_scale")
        else:
            linear(dst + ".mlp.fc1", src + ".mlp.fc1")
            linear(dst + ".mlp.fc2", src + ".mlp.fc2")

    vp = "vision_encoder.encoder.model.visual"
    add("vision.pos_emb", vp + ".pos_embed")
    linear("vision.patch_emb", vp + ".patch_embed.linear")
    linear("vision.post_ln", vp + ".norm")
    linear("vision.proj_mlp.fc1", "vision_encoder.projection.mlp.fc1")
    linear("vision.proj_mlp.fc2", "vision_encoder.projection.mlp.fc2")
    for i in range(config.vision.enc_n_layers):
        dst, src = f"vision.blocks.{i}", f"{vp}.blocks.{i}"
        linear(dst + ".ln1", src + ".norm1")
        linear(dst + ".ln2", src + ".norm2")
        for kind in ("attn.qkv", "attn.proj", "mlp.fc1", "mlp.fc2"):
            linear(dst + "." + kind, src + "." + kind)

    for dst, src in (
        ("coord_encoder", "coordinate_encoder"),
        ("coord_decoder", "coordinate_head"),
        ("size_encoder", "size_encoder"),
        ("size_decoder", "size_head"),
        ("ln", "ln"),
    ):
        linear("region." + dst, "region_model." + src)
    add("region.coord_features", "region_model.coordinate_features.weight", transpose=True)
    add("region.size_features", "region_model.size_features.weight", transpose=True)
    return mapping


def _validate_mapping(torch, model, weights, mapping):
    params = dict(model.named_parameters())
    if set(params) != set(mapping):
        raise ValueError({
            "unmapped_parameters": sorted(set(params) - set(mapping)),
            "unexpected_parameters": sorted(set(mapping) - set(params)),
        })
    consumed = set()
    for dst, (src, scale, transpose) in mapping.items():
        if src not in weights:
            raise ValueError(f"Missing checkpoint weight {src}")
        value = weights[src]
        if not isinstance(value, torch.Tensor) or value.device.type != "cpu":
            raise ValueError(f"Expected CPU tensor for {src}")
        if transpose and value.ndim != 2:
            raise ValueError(f"Only Fourier features can be transposed: {src}")
        shape = tuple(reversed(value.shape)) if transpose else tuple(value.shape)
        if shape != tuple(params[dst].shape):
            raise ValueError(f"Shape mismatch {src} -> {dst}: {shape} != {tuple(params[dst].shape)}")
        consumed.add(src)
        if scale:
            if value.dtype != torch.float8_e4m3fn or value.ndim != 3:
                raise ValueError(f"Expected raw FP8 [expert, output, input] weight: {src}")
            if scale not in weights:
                raise ValueError(f"Missing FP8 channel scale: {scale}")
            scales = weights[scale]
            if tuple(scales.shape) != tuple(value.shape[:2]) or scales.dtype != torch.float32:
                raise ValueError(f"Unexpected channel scale shape/dtype: {scale}")
            if not bool(torch.isfinite(scales).all()) or not bool((scales > 0).all()):
                raise ValueError(f"Nonpositive or nonfinite channel scale: {scale}")
            consumed.add(scale)
        elif value.dtype != torch.bfloat16:
            raise ValueError(f"Unexpected non-expert dtype {value.dtype}: {src}")
    unused = set(weights) - consumed
    allowed = {
        f"text_model.transformer.h.{i}.kv_quantizer.{name}"
        for i in range(model.config.text.n_layers)
        for name in ("_min_val", "_max_val", "_eps_tensor", "k_scale", "v_scale",
                     "_k_initialized", "_v_initialized")
    }
    if unused != allowed:
        raise ValueError({
            "unrecognized_checkpoint_keys": sorted(unused - allowed),
            "missing_kv_quantizer_metadata": sorted(allowed - unused),
        })
    for name in unused:
        if weights[name].ndim != 0:
            raise ValueError(f"Expected scalar KV-quantizer metadata: {name}")
    return params, sorted(unused)


def _dequantize_expert(torch, raw, scales):
    """Exact intended load-time math; scales broadcast over input columns."""
    return (raw.to(torch.float32) * scales[:, None]).to(torch.bfloat16)


def load_reference_model(
    source_dir,
    checkpoint_path,
    tokenizer_path,
    *,
    device="cuda",
    reserve_gib=20,
    max_context=4096,
    dry_run=False,
    progress=None,
):
    """Return (official_model, receipt); dry_run returns an audited meta model.

    No HF wrapper, Photon module, checkpoint conversion file, CUDA graphs or
    compilation is used. A dry run performs CPU mmap/shape validation only.
    Full loads keep BF16 model weights resident on the requested device. The
    caller owns service coordination and a bounded inference supervisor.
    """
    import torch
    from tokenizers import Tokenizer

    started = time.monotonic()
    source_dir, checkpoint_path, tokenizer_path = map(
        Path, (source_dir, checkpoint_path, tokenizer_path)
    )
    reserve_bytes = int(reserve_gib * 1024**3)
    if reserve_bytes < 20 * 1024**3:
        raise ValueError("This Spark comparison must preserve at least 20 GiB")
    if not isinstance(max_context, int) or not 1024 <= max_context <= 4096:
        raise ValueError("Comparison max_context must be between 1024 and 4096")
    available_before = _require_headroom(reserve_bytes, 512 * 1024**2)
    if not checkpoint_path.is_file() or not tokenizer_path.is_file():
        raise FileNotFoundError("Checkpoint and tokenizer must already exist locally")
    tokenizer_hash = hashlib.sha256(tokenizer_path.read_bytes()).hexdigest()
    if tokenizer_hash != STARMIE_SHA256:
        raise ValueError("Tokenizer differs from the audited public Starmie artifact")

    module, config_module, source_hashes = _import_reference(source_dir)
    local_tokenizer = Tokenizer.from_file(str(tokenizer_path))

    class LocalTokenizerOnly:
        @staticmethod
        def from_pretrained(name, *args, **kwargs):
            if name != "moondream/starmie-v1" or args or kwargs:
                raise ValueError("Unexpected tokenizer load requested by reference code")
            return local_tokenizer

    original_tokenizer = module.Tokenizer
    try:
        module.Tokenizer = LocalTokenizerOnly
        config = config_module.MoondreamConfig()
        config = replace(config, text=replace(config.text, max_context=max_context))
        with torch.device("meta"):
            model = module.MoondreamModel(
                config, dtype=torch.bfloat16, setup_caches=False
            )
    finally:
        module.Tokenizer = original_tokenizer
    model.eval().requires_grad_(False)
    weights_raw = torch.load(
        str(checkpoint_path), map_location="cpu", weights_only=True, mmap=True
    )
    if not isinstance(weights_raw, dict):
        raise ValueError("Expected a flat tensor checkpoint dictionary")
    weights = {}
    for name, value in weights_raw.items():
        normalized = name.replace("._orig_mod", "")
        if normalized in weights:
            raise ValueError(f"Duplicate checkpoint name after normalization: {normalized}")
        weights[normalized] = value
    mapping = _mapping(model.config)
    params, unused = _validate_mapping(torch, model, weights, mapping)
    model_bytes = sum(param.numel() * 2 for param in params.values())
    # Stock decode gathers eight BF16 experts (~96 MiB). Allow 4 GiB for
    # buffers, caches, image/prefill activations, allocator and conversion.
    runtime_allowance_bytes = 4 * 1024**3
    receipt = {
        "implementation": "official_preview_pytorch_bf16_from_cached_fp8",
        "upstream_revision": PREVIEW_REVISION,
        "source_dir": str(source_dir.resolve()),
        "source_sha256": source_hashes,
        "checkpoint_path": str(checkpoint_path.resolve()),
        "checkpoint_size_bytes": checkpoint_path.stat().st_size,
        "tokenizer_sha256": tokenizer_hash,
        "checkpoint_tensor_count": len(weights),
        "model_parameter_tensors": len(params),
        "model_parameter_bytes_bf16": model_bytes,
        "expert_tensors_dequantized": sum(scale is not None for _, scale, _ in mapping.values()),
        "ignored_keys": unused,
        "ignored_key_reason": "Official reference uses BF16 KV caches, not quantized KV caches",
        "dequantization": "(FP8.float32 * per_output_channel_FP32_scale).bfloat16; original half-split expert row layout",
        "forward_modified": False,
        "photon_used": False,
        "compile": False,
        "use_flex_decoding": False,
        "max_context": max_context,
        "attention_mask_bytes": max_context * max_context,
        "kv_cache_bytes": 2 * config.text.n_layers * config.text.n_kv_heads * max_context * (config.text.dim // config.text.n_heads) * 2,
        "reserve_bytes": reserve_bytes,
        "mem_available_before_bytes": available_before,
        "runtime_allowance_bytes": runtime_allowance_bytes,
        "minimum_available_for_full_load_bytes": reserve_bytes + model_bytes + runtime_allowance_bytes,
        "dry_run": dry_run,
        "device": "meta" if dry_run else str(device),
    }
    if not dry_run:
        _require_headroom(reserve_bytes, model_bytes + runtime_allowance_bytes)
        target_device = torch.device(device)
        if target_device.type not in {"cpu", "cuda"}:
            raise ValueError("Reference comparison supports only CPU or CUDA")
        with torch.inference_mode():
            for index, (dst, (src, scale, transpose)) in enumerate(mapping.items()):
                needed = params[dst].numel() * 2 + 64 * 1024**2
                _require_headroom(reserve_bytes, needed)
                raw = weights[src]
                if scale is not None:
                    value = torch.empty(raw.shape, dtype=torch.bfloat16, device=target_device)
                    for expert in range(raw.shape[0]):
                        chunk = _dequantize_expert(torch, raw[expert], weights[scale][expert])
                        value[expert].copy_(chunk)
                        del chunk
                else:
                    raw = raw.T if transpose else raw
                    value = raw.to(device=target_device, dtype=torch.bfloat16, copy=True).contiguous()
                parent_name, parameter_name = dst.rsplit(".", 1)
                parent = model.get_submodule(parent_name)
                setattr(parent, parameter_name, torch.nn.Parameter(value, requires_grad=False))
                if progress is not None:
                    progress({"loaded": index + 1, "total": len(mapping), "parameter": dst})
                del value
            # Parameters are materialized; recreate the two nonpersistent meta
            # buffers and BF16 KV caches using official reference methods.
            model._refresh_runtime_buffers()
            model._setup_caches()
        model.use_flex_decoding = False
        if any(p.is_meta for p in model.parameters()) or any(b.is_meta for b in model.buffers()):
            raise RuntimeError("Reference model still has meta parameters or buffers")
        _require_headroom(reserve_bytes)
        if target_device.type == "cuda":
            torch.cuda.synchronize(target_device)
    del weights, weights_raw
    receipt["elapsed_seconds"] = time.monotonic() - started
    receipt["mem_available_after_bytes"] = _available_bytes()
    receipt["cuda_initialized"] = torch.cuda.is_initialized()
    return model, receipt


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CPU-only reference checkpoint mapping audit")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    model, receipt = load_reference_model(
        args.source_dir, args.checkpoint, args.tokenizer, dry_run=True
    )
    Path(args.receipt).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k not in {"source_sha256", "ignored_keys"}}, indent=2))
