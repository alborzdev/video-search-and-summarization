"""CPU segmentation measurements and prompt primitives (NumPy/Pillow only).

Oracle prompts derived from ground truth measure the segmenter conditional on
correct localization. They must never be described as end-to-end perception.
COCO compressed RLE format: cocodataset/cocoapi common/maskApi.c (BSD license).
No model, CUDA, service, network, or pycocotools dependency is imported here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


PROMPT_SOURCES = {"oracle_ground_truth", "moondream_predicted", "manual", "none"}


def decode_coco_rle(rle: dict) -> np.ndarray:
    """Decode compressed ASCII or uncompressed COCO RLE into a Boolean H×W mask.

    COCO runs alternate background/foreground, starting with background, and
    traverse columns first. Counts after index two use a two-run delta code.
    """
    size = rle.get("size")
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or any(type(v) is not int or v <= 0 for v in size)
            or size[0] * size[1] > 16_000_000):
        raise ValueError("RLE size must be positive [height,width], at most 16M pixels")
    encoded = rle.get("counts")
    if isinstance(encoded, bytes):
        encoded = encoded.decode("ascii")
    if isinstance(encoded, str):
        counts, position = [], 0
        while position < len(encoded):
            value, shift = 0, 0
            while True:
                if position >= len(encoded) or shift >= 60:
                    raise ValueError("Truncated or unbounded COCO RLE integer")
                character = ord(encoded[position]) - 48
                position += 1
                if not 0 <= character <= 63:
                    raise ValueError("Invalid COCO RLE character")
                value |= (character & 31) << shift
                shift += 5
                if not character & 32:
                    if character & 16:
                        value |= -1 << shift
                    break
            if len(counts) > 2:
                value += counts[-2]
            counts.append(value)
    elif isinstance(encoded, (list, tuple)):
        counts = list(encoded)
    else:
        raise ValueError("RLE counts must be an ASCII string or integer list")
    if (not counts or any(type(v) is not int or v < 0 for v in counts)
            or sum(counts) != size[0] * size[1]):
        raise ValueError("RLE runs must be nonnegative and cover the complete image")
    flat = np.zeros(size[0] * size[1], dtype=bool)
    position = 0
    for index, count in enumerate(counts):
        if index % 2:
            flat[position:position + count] = True
        position += count
    return flat.reshape(tuple(size), order="F")


def as_binary_mask(value, threshold: float = 0.5) -> np.ndarray:
    """Accept bool, binary integer {0,1}/{0,255}, or probability [0,1] masks.

    There is deliberately no resizing or arbitrary logit threshold heuristic.
    Convert logits explicitly in the model harness before calling this helper.
    """
    array = np.asarray(value)
    if array.ndim != 2 or not array.size or array.size > 16_000_000:
        raise ValueError("Expected a nonempty H×W mask, at most 16M pixels")
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Probability threshold must be finite and in [0,1]")
    if array.dtype == bool:
        return array
    if not np.issubdtype(array.dtype, np.number) or not np.isfinite(array).all():
        raise ValueError("Mask values must be finite numeric values")
    if np.issubdtype(array.dtype, np.integer):
        if np.isin(array, (0, 1)).all():
            return array.astype(bool)
        if np.isin(array, (0, 255)).all():
            return array > 127
        raise ValueError("Integer masks must be binary {0,1} or {0,255}")
    if array.min() < 0 or array.max() > 1:
        raise ValueError("Floating masks must be probabilities in [0,1], not logits")
    return array >= threshold


def mask_bbox(mask) -> list[int] | None:
    """Pixel corners [x0,y0,x1,y1], with exclusive maximum corners."""
    mask = as_binary_mask(mask)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def _interior_pixel(mask: np.ndarray) -> tuple[int, int] | None:
    """Deterministic deep interior pixel using repeated 8-neighbour erosion.

    No SciPy/OpenCV dependency. Ties use distance to the foreground centroid.
    The selected pixel is guaranteed to belong to the supplied Boolean region.
    """
    if not mask.any():
        return None
    current = mask.copy()
    ys, xs = np.nonzero(mask)
    cy, cx = float(ys.mean()), float(xs.mean())
    while True:
        padded = np.pad(current, 1, constant_values=False)
        eroded = np.ones_like(current)
        for dy in range(3):
            for dx in range(3):
                eroded &= padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
        if not eroded.any():
            ys, xs = np.nonzero(current)
            selected = int(np.argmin((ys - cy) ** 2 + (xs - cx) ** 2))
            return int(xs[selected]), int(ys[selected])
        current = eroded


def oracle_prompts_from_mask(mask) -> dict:
    """Ground-truth box and one positive/negative point, explicitly oracle.

    Points use pixel centres (x+.5,y+.5); normalized coordinates divide by
    width/height. The negative is outside this target, potentially on another
    object. These prompts use annotation information unavailable in deployment.
    """
    mask = as_binary_mask(mask)
    height, width = mask.shape
    box = mask_bbox(mask)
    positive, negative = _interior_pixel(mask), _interior_pixel(~mask)
    points, labels = [], []
    for point, label in ((positive, 1), (negative, 0)):
        if point is not None:
            points.append([point[0] + .5, point[1] + .5])
            labels.append(label)
    return {
        "prompt_source": "oracle_ground_truth",
        "end_to_end": False,
        "box_xyxy_pixels": box,
        "box_xyxy_normalized": [box[0]/width, box[1]/height, box[2]/width, box[3]/height] if box else None,
        "points_xy_pixels": points,
        "points_xy_normalized": [[x/width, y/height] for x, y in points],
        "point_labels": labels,
        "positive_point_xy_pixels": [positive[0]+.5, positive[1]+.5] if positive else None,
        "negative_point_xy_pixels": [negative[0]+.5, negative[1]+.5] if negative else None,
        "selection": "deepest 8-neighbour interior; centroid tie break",
    }


def _point_membership(mask, points, coordinate_space):
    height, width = mask.shape
    result = []
    if coordinate_space not in {"pixels", "normalized"}:
        raise ValueError("Point coordinate space must be pixels or normalized")
    for point in points or []:
        if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
            raise ValueError("Points must be finite [x,y] coordinates")
        x, y = map(float, point)
        if coordinate_space == "normalized":
            if not 0 <= x < 1 or not 0 <= y < 1:
                raise ValueError("Normalized point must lie in [0,1)")
            x, y = x * width, y * height
        if not 0 <= x < width or not 0 <= y < height:
            raise ValueError("Point lies outside image")
        result.append(bool(mask[int(y), int(x)]))
    return result


def evaluate_mask(prediction, ground_truth=None, *, prompt_source: str,
                  positive_points=None, negative_points=None,
                  coordinate_space="pixels") -> dict:
    """Pixel scores plus prompt satisfaction; never merges prompt regimes."""
    if prompt_source not in PROMPT_SOURCES:
        raise ValueError(f"prompt_source must be one of {sorted(PROMPT_SOURCES)}")
    pred = as_binary_mask(prediction)
    positive = _point_membership(pred, positive_points, coordinate_space)
    negative = _point_membership(pred, negative_points, coordinate_space)
    result = {
        "prompt_source": prompt_source,
        "oracle_conditioned": prompt_source == "oracle_ground_truth",
        "end_to_end_validated": False,
        "image_size_hw": list(pred.shape),
        "predicted_pixels": int(pred.sum()),
        "predicted_fraction": float(pred.mean()),
        "predicted_bbox_xyxy_pixels": mask_bbox(pred),
        "positive_points_covered": positive,
        "negative_points_incorrectly_covered": negative,
        "point_constraints_satisfied": all(positive) and not any(negative),
        "quality_scope": "annotated_target" if ground_truth is not None else "qualitative_only",
    }
    if ground_truth is None:
        result["iou"] = None
        return result
    gt = as_binary_mask(ground_truth)
    if pred.shape != gt.shape:
        raise ValueError(f"Prediction/ground-truth shape mismatch: {pred.shape} != {gt.shape}; resize explicitly")
    intersection, union = int((pred & gt).sum()), int((pred | gt).sum())
    tp, fp, fn, tn = intersection, int((pred & ~gt).sum()), int((~pred & gt).sum()), int((~pred & ~gt).sum())
    result.update({
        "ground_truth_pixels": int(gt.sum()), "intersection_pixels": intersection,
        "union_pixels": union, "iou": intersection/union if union else 1.0,
        "empty_union_policy": "IoU=1 only when both masks are empty; inspect false-positive area separately",
        "true_positive_pixels": tp, "false_positive_pixels": fp,
        "false_negative_pixels": fn, "true_negative_pixels": tn,
        "precision": tp/(tp+fp) if tp+fp else None,
        "recall": tp/(tp+fn) if tp+fn else None,
        "negative_image_false_positive_fraction": float(pred.mean()) if not gt.any() else None,
        "ground_truth_positive_points_valid": _point_membership(gt, positive_points, coordinate_space),
        "ground_truth_negative_points_invalid": _point_membership(gt, negative_points, coordinate_space),
    })
    return result


def binary_iou(prediction, ground_truth) -> float:
    return evaluate_mask(prediction, ground_truth, prompt_source="none")["iou"]


def save_overlay(image, prediction, output_path, ground_truth=None, *, alpha=.45,
                 points_xy_pixels=None, point_labels=None) -> dict:
    """Save visual evidence: green=TP, orange=FP, blue=FN; teal if no GT."""
    source = Image.open(image).convert("RGB") if isinstance(image, (str, Path)) else image.convert("RGB")
    pred = as_binary_mask(prediction)
    if pred.shape != (source.height, source.width):
        raise ValueError("Overlay mask and image dimensions must match")
    if not 0 <= alpha <= 1:
        raise ValueError("Overlay alpha must be in [0,1]")
    colors = np.zeros((source.height, source.width, 3), dtype=np.uint8)
    if ground_truth is None:
        selected = pred
        colors[pred] = (0, 211, 190)
        legend = {"prediction_only": "teal"}
    else:
        gt = as_binary_mask(ground_truth)
        if gt.shape != pred.shape:
            raise ValueError("Overlay ground-truth dimensions must match")
        selected = pred | gt
        colors[pred & gt] = (44, 203, 94)
        colors[pred & ~gt] = (255, 137, 35)
        colors[~pred & gt] = (65, 145, 255)
        legend = {"true_positive": "green", "false_positive": "orange", "false_negative": "blue"}
    pixels = np.asarray(source).copy()
    pixels[selected] = np.rint((1-alpha)*pixels[selected] + alpha*colors[selected]).astype(np.uint8)
    result = Image.fromarray(pixels)
    if points_xy_pixels:
        if point_labels is None or len(point_labels) != len(points_xy_pixels):
            raise ValueError("Each overlay point needs a positive/negative label")
        draw = ImageDraw.Draw(result)
        for (x, y), label in zip(points_xy_pixels, point_labels):
            if label not in (0, 1):
                raise ValueError("Point labels must be 0 or 1")
            color = "lime" if label else "red"
            draw.ellipse((x-4, y-4, x+4, y+4), fill=color, outline="white", width=1)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path)
    return {"path": str(output_path.resolve()), "legend": legend, "alpha": alpha}


def load_mask(path):
    path = Path(path)
    value = np.load(path, allow_pickle=False) if path.suffix == ".npy" else np.asarray(Image.open(path))
    return as_binary_mask(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction", required=True, help="Binary PNG or probability/bool NPY in original image resolution")
    parser.add_argument("--ground-truth")
    parser.add_argument("--prompt-source", required=True, choices=sorted(PROMPT_SOURCES))
    parser.add_argument("--prompts-json", help="Optional oracle/actual prompt record; points_xy_pixels and point_labels")
    parser.add_argument("--image")
    parser.add_argument("--overlay")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    pred = load_mask(args.prediction)
    gt = load_mask(args.ground_truth) if args.ground_truth else None
    prompts = json.loads(Path(args.prompts_json).read_text()) if args.prompts_json else {}
    if prompts.get("prompt_source", args.prompt_source) != args.prompt_source:
        raise ValueError("Prompt record and declared prompt source disagree")
    points, labels = prompts.get("points_xy_pixels", []), prompts.get("point_labels", [])
    if len(points) != len(labels) or any(label not in (0, 1) for label in labels):
        raise ValueError("Prompt point labels must match points and be binary")
    result = evaluate_mask(pred, gt, prompt_source=args.prompt_source,
        positive_points=[p for p, label in zip(points, labels) if label],
        negative_points=[p for p, label in zip(points, labels) if not label])
    if args.overlay:
        if not args.image:
            raise ValueError("--image is required for an overlay")
        result["overlay"] = save_overlay(args.image, pred, args.overlay, gt,
            points_xy_pixels=points, point_labels=labels)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
