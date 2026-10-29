"""Small, local-only adapters for official SAM 2.1 Tiny and EdgeTAM.

Each candidate must run in its own process: both official source trees use the
package name ``sam2``. Weights remain FP32; CUDA inference uses BF16 autocast.
All input point/box coordinates are normalized to [0, 1]. Text prompts must be
resolved into a point or box by the caller; this adapter does no text detection.
"""

from __future__ import annotations

from contextlib import nullcontext
import hashlib
import importlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".spark/local-segmentation"
CONFIGS = {
    "sam2.1-tiny": "configs/sam2.1/sam2.1_hiera_t.yaml",
    "edgetam": "configs/edgetam.yaml",
}
MAX_IMAGE_PIXELS = 16_000_000


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024**2):
            digest.update(chunk)
    return digest.hexdigest()


def _reserve_gib():
    saved_reserve = json.loads((ROOT / ".spark/settings.json").read_text())["reserve_gib"]
    if (isinstance(saved_reserve, bool) or not isinstance(saved_reserve, (int, float))
            or not math.isfinite(saved_reserve) or saved_reserve < 0):
        raise RuntimeError("Saved Spark memory reserve must be a finite nonnegative number")
    return saved_reserve


def _memory_check(extra_bytes=0):
    reserve_gib = _reserve_gib()
    available = next(int(line.split()[1]) * 1024
                     for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    if available < reserve_gib * 1024**3 + extra_bytes:
        raise RuntimeError(f"Local segmentation would breach the {reserve_gib:g} GiB reserve")
    return available


def _rgb(image):
    import numpy as np
    from PIL import Image

    if isinstance(image, Image.Image):
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("Images must contain at most 16 megapixels")
        image = np.asarray(image.convert("RGB"))
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
            or image.ndim != 3 or image.shape[2] != 3
            or min(image.shape[:2]) < 1):
        raise ValueError("Image must be a PIL image or nonempty uint8 RGB HxWx3 array")
    if image.shape[0] * image.shape[1] > MAX_IMAGE_PIXELS:
        raise ValueError("Images must contain at most 16 megapixels")
    rgb = np.ascontiguousarray(image)
    return rgb if rgb.flags.writeable else rgb.copy()


def _prompt(box=None, points=None, labels=None):
    import numpy as np

    if box is None and points is None:
        raise ValueError("Supply a normalized box or point prompt")
    parsed_box = None
    if box is not None:
        parsed_box = np.asarray(box, dtype=np.float32)
        if (parsed_box.shape != (4,) or not np.isfinite(parsed_box).all()
                or (parsed_box < 0).any() or (parsed_box > 1).any()
                or parsed_box[0] >= parsed_box[2] or parsed_box[1] >= parsed_box[3]):
            raise ValueError("box must be [x1,y1,x2,y2] in [0,1] with positive area")
    parsed_points = parsed_labels = None
    if points is not None:
        parsed_points = np.asarray(points, dtype=np.float32)
        if (parsed_points.ndim != 2 or parsed_points.shape[1] != 2
                or len(parsed_points) == 0 or not np.isfinite(parsed_points).all()
                or (parsed_points < 0).any() or (parsed_points > 1).any()):
            raise ValueError("points must be nonempty Nx2 normalized coordinates")
        parsed_labels = (np.ones(len(parsed_points), dtype=np.int32) if labels is None
                         else np.asarray(labels))
        if (parsed_labels.shape != (len(parsed_points),)
                or not np.isin(parsed_labels, [0, 1]).all()):
            raise ValueError("labels must contain one foreground(1)/background(0) label per point")
        parsed_labels = parsed_labels.astype(np.int32)
    elif labels is not None:
        raise ValueError("labels require points")
    return parsed_box, parsed_points, parsed_labels


class Segmenter:
    def __init__(self, predictor, receipt):
        self.predictor = predictor
        self.receipt = receipt
        self._shapes = []
        self._batch = False

    def _sync(self):
        import torch
        if self.predictor.device.type == "cuda":
            torch.cuda.synchronize(self.predictor.device)

    def _autocast(self):
        import torch
        return (torch.autocast("cuda", dtype=torch.bfloat16)
                if self.predictor.device.type == "cuda" else nullcontext())

    def set_image(self, image):
        """Encode one image once; subsequent predict() calls reuse its features."""
        import torch
        rgb = _rgb(image)
        _memory_check(512 * 1024**2)
        self._sync()
        started = time.perf_counter()
        with torch.inference_mode(), self._autocast():
            self.predictor.set_image(rgb)
        self._sync()
        self._shapes, self._batch = [rgb.shape[:2]], False
        return {"encode_ms": (time.perf_counter() - started) * 1000,
                "image_shape": list(rgb.shape[:2]), "batch_size": 1}

    def set_images(self, images):
        """Batch image encoding; pair with predict_batch(), one prompt per image."""
        import torch
        rgbs = [_rgb(image) for image in images]
        if not 1 <= len(rgbs) <= 8:
            raise ValueError("Image batches must contain 1 to 8 images")
        _memory_check(len(rgbs) * 512 * 1024**2)
        self._sync()
        started = time.perf_counter()
        with torch.inference_mode(), self._autocast():
            self.predictor.set_image_batch(rgbs)
        self._sync()
        self._shapes, self._batch = [rgb.shape[:2] for rgb in rgbs], True
        return {"encode_ms": (time.perf_counter() - started) * 1000,
                "image_shapes": [list(s) for s in self._shapes], "batch_size": len(rgbs)}

    @staticmethod
    def _result(masks, scores, shape, decode_ms):
        import numpy as np
        scores = np.asarray(scores).reshape(-1)
        masks = np.asarray(masks).reshape((-1,) + tuple(shape))
        if len(scores) != len(masks) or not len(scores) or not np.isfinite(scores).all():
            raise RuntimeError("Unexpected model mask/score output")
        index = int(scores.argmax())
        mask = masks[index].astype(bool)
        return {"mask": mask, "score": float(scores[index]),
                "score_kind": "uncalibrated_predicted_mask_iou",
                "candidate_scores": scores.tolist(), "selected_candidate": index,
                "candidate_count": len(scores),
                "mask_area": int(mask.sum()), "mask_fraction": float(mask.mean()),
                "decode_ms": decode_ms}

    def predict(self, *, box=None, points=None, labels=None, multimask=False):
        import torch
        if not self._shapes or self._batch:
            raise RuntimeError("Call set_image() before predict()")
        box, points, labels = _prompt(box, points, labels)
        _memory_check(128 * 1024**2)
        self._sync()
        started = time.perf_counter()
        with torch.inference_mode(), self._autocast():
            masks, scores, _ = self.predictor.predict(
                point_coords=points, point_labels=labels, box=box,
                multimask_output=multimask, return_logits=False,
                # Coordinates already normalized; upstream scales by 1024.
                normalize_coords=False,
            )
        self._sync()
        return self._result(masks, scores, self._shapes[0],
                            (time.perf_counter() - started) * 1000)

    def predict_batch(self, prompts, *, multimask=False):
        import torch
        if not self._batch or len(prompts) != len(self._shapes):
            raise RuntimeError("Call set_images(); supply one prompt per encoded image")
        parsed = [_prompt(p.get("box"), p.get("points"), p.get("labels")) for p in prompts]
        _memory_check(128 * 1024**2)
        self._sync()
        started = time.perf_counter()
        with torch.inference_mode(), self._autocast():
            masks, scores, _ = self.predictor.predict_batch(
                box_batch=[p[0] for p in parsed],
                point_coords_batch=[p[1] for p in parsed],
                point_labels_batch=[p[2] for p in parsed],
                multimask_output=multimask, return_logits=False, normalize_coords=False,
            )
        self._sync()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {"results": [self._result(m, s, shape, None)
                            for m, s, shape in zip(masks, scores, self._shapes)],
                "decode_ms": elapsed_ms, "batch_size": len(prompts)}


def load(name="sam2.1-tiny", *, device="cuda", state_dir=STATE):
    """Load an official local checkpoint strictly; does not download anything."""
    import torch
    if name not in CONFIGS:
        raise ValueError(f"Choose one of {tuple(CONFIGS)}")
    _memory_check()
    manifest = json.loads((Path(state_dir) / "manifest.json").read_text())
    entry = manifest["models"][name]
    source = Path(entry["source_dir"]).resolve()
    checkpoint = Path(entry["checkpoint"]["path"])
    if _sha256(checkpoint) != entry["checkpoint"]["sha256"]:
        raise ValueError("Checkpoint SHA256 differs from the staging manifest")
    for item in entry["source_files"]:
        if _sha256(source / item["path"]) != item["sha256"]:
            raise ValueError("Official source changed: " + item["path"])
    if "sam2" in sys.modules:
        existing = Path(sys.modules["sam2"].__file__).resolve().parent
        if existing != source / "sam2":
            raise RuntimeError("Use a fresh subprocess for each candidate's official sam2 package")
    else:
        sys.path.insert(0, str(source))
    build = importlib.import_module("sam2.build_sam")
    predictor_module = importlib.import_module("sam2.sam2_image_predictor")
    backbone = original_create_model = None
    if name == "edgetam":
        # The complete official EdgeTAM checkpoint contains all backbone keys.
        # Avoid fetching an unrelated initialization checkpoint immediately
        # overwritten by strict full-model loading. No forward code is changed.
        backbone = importlib.import_module("sam2.modeling.backbones.timm")
        original_create_model = backbone.create_model

        def local_initialization_only(*args, **kwargs):
            kwargs["pretrained"] = False
            return original_create_model(*args, **kwargs)

        backbone.create_model = local_initialization_only
    started = time.perf_counter()
    try:
        model = build.build_sam2(
            CONFIGS[name], str(checkpoint), device=device, mode="eval",
            apply_postprocessing=False,
        )
    finally:
        if backbone is not None:
            backbone.create_model = original_create_model
    model.requires_grad_(False)
    predictor = predictor_module.SAM2ImagePredictor(
        model, mask_threshold=0.0, max_hole_area=0.0, max_sprinkle_area=0.0
    )
    if predictor.device.type == "cuda":
        torch.cuda.synchronize(predictor.device)
    _memory_check()
    versions = {p: importlib.metadata.version(p) for p in
                ["torch", "torchvision", "hydra-core", "omegaconf", "iopath", "timm"]}
    receipt = {
        "name": name, "device": str(predictor.device),
        "source_repository": entry["repo"], "source_revision": entry["revision"],
        "source_sha256": {f["path"]: f["sha256"] for f in entry["source_files"]},
        "checkpoint_sha256": entry["checkpoint"]["sha256"],
        "checkpoint_path": str(checkpoint), "checkpoint_bytes": checkpoint.stat().st_size,
        "config": CONFIGS[name], "versions": versions,
        "load_ms": (time.perf_counter() - started) * 1000,
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "parameter_dtypes": sorted({str(p.dtype) for p in model.parameters()}),
        "autocast": "bfloat16" if predictor.device.type == "cuda" else None,
        "strict_checkpoint_load": True, "forward_modified": False,
        "backbone_pretrained_download_suppressed": name == "edgetam",
        "compile_image_encoder": False,
        "postprocessing_stability_fallback": False,
        "hole_and_sprinkle_cleanup": False,
        "reserve_gib": _reserve_gib(),
    }
    return Segmenter(predictor, receipt)
