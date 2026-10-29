"""Diagnostic segmentation decoder for the official Moondream PyTorch model.

The public Preview reference has no segment API. This module supplies the
documented segment prompt and typed spatial feedback while using its original
vision encoder, text decoder, region heads and full vocabulary projection.
It does not import Photon/Kestrel or alter weights. Default decoding is greedy
and unconditioned. ``condition_svg`` is an explicit, nonstandard comparison.

Protocol: https://arxiv.org/html/2604.02593v1 (Appendix A.1).
Reference: moondream/moondream3-preview, revision
5112966d1a723413b1c9a1e8bea272b72e647b35, moondream.py and region.py.
"""

from importlib import import_module
import math
import re


_PATH_ARITY = {"M": 2, "L": 2, "C": 6, "Z": 0}


def _prompt_ids(tokenizer, object_name, spatial_refs=None):
    """Image encoding already provides BOS and image tokens; do not repeat BOS."""
    if not isinstance(object_name, str) or not object_name.strip():
        raise ValueError("object must be nonempty text")
    refs = []
    for ref in spatial_refs or []:
        if len(ref) not in (2, 4):
            raise ValueError("spatial references must be points or bounding boxes")
        if any(isinstance(v, bool) or not isinstance(v, (float, int))
               or not math.isfinite(v) or not 0 <= v <= 1 for v in ref):
            raise ValueError("spatial references must contain normalized numbers")
        if len(ref) == 4 and (ref[2] <= ref[0] or ref[3] <= ref[1]):
            raise ValueError("spatial reference boxes must have positive area")
        refs.append(tuple(float(v) for v in ref))
    ids = [1, 17374, 2]
    for ref in refs:
        ids.extend([5, 5] if len(ref) == 2 else [5, 5, 6])
    ids.extend(tokenizer.encode(object_name.strip()).ids)
    ids.append(3)
    return ids, refs


def _svg_path(tokenizer, token_ids):
    """Decode the paper's integer M/L/C/Z grammar in bbox-relative units.

    Each integer is a complete vocabulary token, so decoding a concatenated
    string can destroy numeric boundaries. Reserved markers, including the
    observed 10/11 path delimiters, are excluded from path text.
    """
    pieces = [tokenizer.decode([int(t)], skip_special_tokens=True).strip()
              for t in token_ids if t > 20]
    pieces = [p for p in pieces if p]
    if not pieces:
        return "", pieces
    symbols = []
    negative = False
    for piece in pieces:
        if piece == "-":
            if negative:
                raise ValueError("Repeated SVG minus sign")
            negative = True
        elif re.fullmatch(r"[+-]?\d+", piece):
            value = int(piece)
            if negative:
                if piece[0] in "+-":
                    raise ValueError("Duplicate SVG number sign")
                value = -value
            negative = False
            if abs(value) > 1_000_000:
                raise ValueError("Unbounded SVG coordinate")
            symbols.append(value)
        elif len(piece) == 1 and piece.upper() in _PATH_ARITY:
            if negative:
                raise ValueError("SVG minus sign has no number")
            symbols.append(piece)
        else:
            raise ValueError(f"Unsupported SVG vocabulary token: {piece!r}")
    if negative:
        raise ValueError("SVG path ends with a minus sign")
    if not symbols or symbols[0] not in ("M", "m"):
        raise ValueError("SVG path must begin with a move command")
    index = 0
    while index < len(symbols):
        command = symbols[index]
        if not isinstance(command, str):
            raise ValueError("Expected an SVG command")
        index += 1
        start = index
        while index < len(symbols) and isinstance(symbols[index], int):
            index += 1
        count = index - start
        arity = _PATH_ARITY[command.upper()]
        if (arity == 0 and count) or (arity and (not count or count % arity)):
            raise ValueError("SVG path contains an incomplete command")
    path = " ".join(s if isinstance(s, str) else format(s / 960.0, ".9g")
                    for s in symbols)
    return path, pieces


def _bbox(coords, sizes):
    if len(coords) < 2 or not sizes:
        return None, None
    cx, cy = coords[:2]
    width, height = sizes[0]
    raw = {"x_min": cx - width / 2, "y_min": cy - height / 2,
           "x_max": cx + width / 2, "y_max": cy + height / 2}
    return {k: min(1.0, max(0.0, v)) for k, v in raw.items()}, raw


def segment(model, image, object, spatial_refs=None, max_tokens=256,
            condition_svg=False):
    """Return raw generation evidence and an independently decoded coarse SVG.

    ``model`` can be the official MoondreamModel or its HfMoondream wrapper.
    The caller owns model/cache/device setup, memory supervision and rendering.
    Conditioning forces token 10 once immediately after coord/coord/size. It
    is never enabled implicitly, and the unmodified logits remain in the trace.
    """
    import torch

    if not hasattr(model, "_prefill_prompt"):
        model = model.model
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")
    ref = import_module(type(model).__module__)
    prompt_ids, refs = _prompt_ids(model.tokenizer, object, spatial_refs)
    token_ids, raw_tokens, coords, sizes = [], [], [], []
    post_bbox = None
    forced_boundary = False
    finish_reason = "max_tokens"
    max_context = model.config.text.max_context

    with torch.inference_mode():
        encoded = model.encode_image(image)
        model.load_encoded_image(encoded)
        if encoded.pos + len(prompt_ids) >= max_context:
            raise ValueError("Image and prompt exhaust the reference context")
        prompt = torch.tensor([prompt_ids], device=model.device, dtype=torch.long)
        logits, hidden, _, pos = model._prefill_prompt(
            prompt, encoded.pos, temperature=0, top_p=1,
            spatial_refs=refs or None, lora=None)
        hidden = hidden[:, -1:, :]
        mask = torch.zeros(1, 1, max_context, device=model.device, dtype=torch.bool)
        mask[:, :, :pos] = True
        pos_ids = torch.tensor([pos], device=model.device, dtype=torch.long)

        for index in range(max_tokens):
            probabilities = torch.softmax(logits[0].float(), dim=-1)
            greedy_id = int(torch.argmax(logits[0]).item())
            after_bbox = token_ids == [5, 5, 6]
            token_id = 10 if condition_svg and after_bbox else greedy_id
            forced = bool(condition_svg and after_bbox)
            if after_bbox:
                best = torch.topk(probabilities, 8)
                post_bbox = {
                    "greedy_token_id": greedy_id,
                    "eos_probability": float(probabilities[0].item()),
                    "svg_start_probability": float(probabilities[10].item()),
                    "M_probability": float(probabilities[65].item()),
                    "top_tokens": [{"id": int(i), "probability": float(p)}
                                   for i, p in zip(best.indices.tolist(), best.values.tolist())],
                    "forced_svg_start": forced,
                }
            forced_boundary |= forced
            entry = {"index": index, "token_id": token_id,
                     "greedy_token_id": greedy_id, "forced": forced,
                     "probability": float(probabilities[token_id].item())}
            token_ids.append(token_id)
            raw_tokens.append(entry)
            if token_id == 0:
                finish_reason = "eos"
                break
            if token_id == 5:
                coordinate_logits = ref.decode_coordinate(hidden, model.region)
                value = torch.argmax(coordinate_logits, dim=-1) / coordinate_logits.size(-1)
                scalar = float(value.item())
                coords.append(scalar)
                entry.update(kind="coordinate", value=scalar)
                next_emb = ref.encode_coordinate(
                    value.to(dtype=coordinate_logits.dtype), model.region).unsqueeze(0)
            elif token_id == 6:
                size_logits = ref.decode_size(hidden, model.region)
                bins = torch.argmax(size_logits, dim=-1)
                values = torch.pow(2.0, bins.float() / 1023.0 * 10.0 - 10.0)
                pair = [float(v) for v in values.tolist()]
                sizes.append(pair)
                entry.update(kind="size", value=pair)
                next_emb = ref.encode_size(values.to(dtype=size_logits.dtype), model.region)
                next_emb = next_emb.unsqueeze(0).unsqueeze(0)
            else:
                entry.update(kind="text", text=model.tokenizer.decode(
                    [token_id], skip_special_tokens=False))
                next_emb = ref.text_encoder(
                    torch.tensor([[token_id]], device=model.device, dtype=torch.long),
                    model.text)
            if index + 1 >= max_tokens:
                break
            if pos >= max_context:
                finish_reason = "context_limit"
                break
            mask[:, :, pos] = True
            pos_ids[0] = pos
            # No point_gen_indices: the full vocabulary must remain available.
            logits, hidden = model._decode_one_tok(
                next_emb, mask, pos_ids, lora=None, lm_head_indices=None)
            hidden = hidden[:, -1:, :]
            pos += 1

    bbox, unclipped_bbox = _bbox(coords, sizes)
    parse_error = None
    try:
        path, path_tokens = _svg_path(model.tokenizer, token_ids)
    except ValueError as exc:
        path, path_tokens = "", []
        parse_error = str(exc)
    result = {
        "diagnostic_decoder": True,
        "implementation": "official_pytorch_model_with_custom_segment_loop",
        "condition_svg": bool(condition_svg),
        "forced_boundary": forced_boundary,
        "object": object.strip(), "spatial_refs": [list(r) for r in refs],
        "prompt_token_ids": prompt_ids, "image_prefix_tokens": int(encoded.pos),
        "token_ids": token_ids, "raw_tokens": raw_tokens,
        "post_bbox": post_bbox, "bbox": bbox, "unclipped_bbox": unclipped_bbox,
        "path": path, "svg_path": path, "path_tokens": path_tokens,
        "finish_reason": finish_reason, "output_tokens": len(token_ids),
        "refined": False, "quality_validated": False,
    }
    if parse_error:
        result["parse_error"] = parse_error
    return result
