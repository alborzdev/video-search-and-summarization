"""Local Moondream grounding followed by a separately measured mask model.

This is a synchronous, single-caller API, not a server. Model construction is
lazy and never downloads weights. Run it under the existing Spark supervisor
and memory guard. Each segmenter family needs a fresh process because their
official source trees share the ``sam2`` import namespace.

``presence_mode='off'`` exposes the grounding model's ordinary behavior without an
unqualified extra classifier. ``'query'`` adds a real yes/no Moondream query:
only an exact yes permits grounding; no and unrecognized answers produce no
masks. Neither mode establishes calibrated absence detection. Qualify them
against negative controls before choosing a deployment default.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".spark/moondream-photon"
MODEL_POINTERS = {
    "moondream2": "md2-model-path.txt",
    "moondream3-preview": "preview-model-path.txt",
    "moondream3.1-9B-A2B": "model-path.txt",
}
SEGMENTERS = ("edgetam", "sam2.1-tiny")
MAX_IMAGE_PIXELS = 16_000_000


def _reserve_gib():
    reserve = json.loads((ROOT / ".spark/settings.json").read_text())["reserve_gib"]
    if (isinstance(reserve, bool) or not isinstance(reserve, (int, float))
            or not math.isfinite(reserve) or reserve < 0):
        raise RuntimeError("Saved Spark memory reserve must be a finite nonnegative number")
    return reserve


def _check_memory(extra_gib=0):
    reserve = _reserve_gib()
    available = next(int(line.split()[1]) * 1024
                     for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    if available < (reserve + extra_gib) * 1024**3:
        raise RuntimeError(f"Moondream bridge would breach the {reserve:g} GiB reserve")


def _sync(device):
    # CPU unit tests do not import Torch. The real loader imports it before use.
    torch = sys.modules.get("torch")
    if torch is not None and device.startswith("cuda") and torch.cuda.is_initialized():
        torch.cuda.synchronize(device)


def _local_pointer(state_dir, filename):
    value = (Path(state_dir) / filename).read_text().strip()
    if not value:
        raise ValueError(f"Empty local checkpoint pointer: {filename}")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(state_dir) / path
    if not path.is_file():
        raise FileNotFoundError(f"Staged local artifact is missing: {path}")
    # Photon dispatches checkpoint readers by filename extension. HF cache
    # snapshot symlinks have that extension; their blob targets usually do not.
    return str(path.absolute())


def _load_photon(*, model, state_dir, device, gb10_compat):
    _check_memory()
    model_path = _local_pointer(state_dir, MODEL_POINTERS[model])
    tokenizer_path = _local_pointer(state_dir, "tokenizer-path.txt")
    import moondream as md

    compatibility = None
    if gb10_compat:
        # Explicit per-process opt-in; vendor files and GPU identity stay intact.
        from tools.moondream.gb10_compat import install_gb10_compat
        compatibility = install_gb10_compat()
    client = md.photon(
        model, model_path=model_path, tokenizer_path=tokenizer_path,
        device=device, max_batch_size=1,
        kv_cache_pages=2048 if model == "moondream2" else 4096,
        enable_cuda_graphs=False, enable_prefix_cache=False, decode_path="native",
    )
    return client, {
        "model": model, "model_path": model_path, "tokenizer_path": tokenizer_path,
        "device": device, "runtime": "photon", "gb10_compat": compatibility,
        "enable_cuda_graphs": False, "enable_prefix_cache": False,
        "max_batch_size": 1, "reserve_gib": _reserve_gib(),
    }


def _load_segmenter(name, *, device, state_dir=None):
    from tools.segmentation.adapter import load
    kwargs = {"device": device}
    if state_dir is not None:
        kwargs["state_dir"] = state_dir
    return load(name, **kwargs)


def _object_text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError("object must be nonempty text of at most 512 characters")
    return value.strip()


def _prepare_image(image):
    from PIL import Image
    import numpy as np

    if isinstance(image, Image.Image):
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("Images must contain at most 16 megapixels")
        image = image.convert("RGB")
    elif (isinstance(image, np.ndarray) and image.dtype == np.uint8
          and image.ndim == 3 and image.shape[2] == 3):
        if image.shape[0] * image.shape[1] > MAX_IMAGE_PIXELS:
            raise ValueError("Images must contain at most 16 megapixels")
        image = Image.fromarray(np.ascontiguousarray(image))
    else:
        raise ValueError("Image must be a PIL image or uint8 RGB HxWx3 array")
    if image.width < 1 or image.height < 1:
        raise ValueError("Image must not be empty")
    return image


def _presence_answer(raw):
    """Do not interpret explanations, hedges or substrings as affirmative."""
    answer = raw.get("answer") if isinstance(raw, dict) else None
    if not isinstance(answer, str):
        return None
    match = re.fullmatch(r"(yes|no)[.!]?", answer.strip(), flags=re.IGNORECASE)
    return None if match is None else match.group(1).lower() == "yes"


def _coordinates(item, keys):
    if not isinstance(item, dict):
        raise ValueError("grounding entry must be an object")
    values = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number")
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{key} must be finite and normalized to [0,1]")
        values.append(value)
    if len(values) == 4 and (values[0] >= values[2] or values[1] >= values[3]):
        raise ValueError("bounding box must have positive area")
    return values


class MoondreamBridge:
    """Reuse one Moondream model and one lazily loaded mask model.

    Returned masks are full-image NumPy boolean arrays. ``raw_grounding`` is
    the untouched Moondream result. Coordinates passed to the mask adapter
    remain normalized; that adapter performs the model-coordinate transform.
    Loader injection is for CPU orchestration tests, not an inference backend.
    """

    def __init__(self, model="moondream2", segmenter_name="edgetam", *,
                 presence_mode="off", max_objects=3, gb10_compat=False,
                 state_dir=STATE, segmenter_state_dir=None, device="cuda",
                 _client_loader=None, _segmenter_loader=None):
        if model not in MODEL_POINTERS:
            raise ValueError(f"model must be one of {tuple(MODEL_POINTERS)}")
        if segmenter_name not in SEGMENTERS:
            raise ValueError(f"segmenter_name must be one of {SEGMENTERS}")
        if presence_mode not in ("off", "query"):
            raise ValueError("presence_mode must be 'off' or 'query'")
        if type(max_objects) is not int or not 1 <= max_objects <= 3:
            raise ValueError("max_objects must be between 1 and 3")
        if model != "moondream2" and not gb10_compat:
            raise ValueError(f"{model} on Spark requires explicit gb10_compat=True")
        if model == "moondream2" and gb10_compat:
            raise ValueError("Moondream2 uses stock Photon; GB10 MoE compatibility is for Moondream3")
        self.model = model
        self.segmenter_name = segmenter_name
        self.presence_mode = presence_mode
        self.max_objects = max_objects
        self.gb10_compat = gb10_compat
        self.state_dir = Path(state_dir)
        self.segmenter_state_dir = segmenter_state_dir
        self.device = str(device)
        self._client_loader = _client_loader or _load_photon
        self._segmenter_loader = _segmenter_loader or _load_segmenter
        self._client = self._segmenter = None
        self._client_receipt = None
        self._closed = False

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._closed:
            return
        try:
            if self._client is not None:
                self._client.close()
        finally:
            self._client = self._segmenter = None
            self._closed = True

    def _check_open(self):
        if self._closed:
            raise RuntimeError("MoondreamBridge is closed")

    def _timed(self, result, stage, function):
        _check_memory(0.5)
        _sync(self.device)
        start = time.perf_counter()
        value = function()
        _sync(self.device)
        result["timings_ms"][stage] += (time.perf_counter() - start) * 1000
        return value

    def _ensure_client(self, result):
        if self._client is None:
            self._client, self._client_receipt = self._timed(
                result, "moondream_load", lambda: self._client_loader(
                    model=self.model, state_dir=self.state_dir, device=self.device,
                    gb10_compat=self.gb10_compat))
        result["moondream_receipt"] = copy.deepcopy(self._client_receipt)
        return self._client

    def _start(self, image, operation, object=None):
        self._check_open()
        started = time.perf_counter()
        image = _prepare_image(image)
        result = {
            "operation": operation, "model": self.model, "object": object,
            "status": "ok", "image": {"width": image.width, "height": image.height,
                "rgb_sha256": hashlib.sha256(image.tobytes()).hexdigest()},
            "timings_ms": {key: 0.0 for key in (
                "preprocess", "moondream_load", "describe", "presence", "detect",
                "point", "segmenter_load", "image_encode", "mask_decode", "total")},
        }
        result["timings_ms"]["preprocess"] = (time.perf_counter() - started) * 1000
        return image, result, started

    @staticmethod
    def _finish(result, started):
        result["timings_ms"]["total"] = (time.perf_counter() - started) * 1000
        return result

    def describe(self, image):
        image, result, started = self._start(image, "describe")
        client = self._ensure_client(result)
        raw = self._timed(result, "describe", lambda: client.query(
            image, "Describe the visible scene and objects.", settings={"max_tokens": 96}))
        if not isinstance(raw, dict) or not isinstance(raw.get("answer"), str):
            raise RuntimeError("Moondream description response has no text answer")
        result.update(description=raw["answer"], raw_response=copy.deepcopy(raw))
        return self._finish(result, started)

    def _ground(self, client, image, object, result, kind):
        # Detect ignores max_tokens. Both spatial skills support max_objects,
        # which bounds decoding before generation rather than slicing later.
        settings = {"max_objects": self.max_objects}
        raw = self._timed(result, kind, lambda: getattr(client, kind)(
            image, object, settings=settings))
        key = "objects" if kind == "detect" else "points"
        if not isinstance(raw, dict) or not isinstance(raw.get(key), list):
            raise RuntimeError(f"Moondream {kind} response has no {key} list")
        result["raw_grounding"] = copy.deepcopy(raw)
        result["grounding_settings"] = settings
        result["grounding_generation_limit"] = self.max_objects
        # The public SDK strips the finish reason. An output at the cap may
        # be incomplete; it is not evidence that only this many objects exist.
        result["grounding_returned_at_limit"] = len(raw[key]) >= self.max_objects
        fields = ("x_min", "y_min", "x_max", "y_max") if kind == "detect" else ("x", "y")
        valid, rejected = [], []
        for index, item in enumerate(raw[key]):
            try:
                coords = _coordinates(item, fields)
            except ValueError as exc:
                rejected.append({"source_index": index, "reason": str(exc)})
                continue
            valid.append({"source_index": index, "grounding": copy.deepcopy(item),
                          "box" if kind == "detect" else "point": coords})
        result.update(rejected_grounding=rejected, valid_grounding_count=len(valid),
                      truncated=len(valid) > self.max_objects)
        if not valid:
            result["status"] = "invalid_grounding" if rejected else "no_detections"
        return valid[:self.max_objects]

    def detect(self, image, object):
        object = _object_text(object)
        image, result, started = self._start(image, "detect", object)
        client = self._ensure_client(result)
        result["objects"] = self._ground(client, image, object, result, "detect")
        return self._finish(result, started)

    def point(self, image, object):
        object = _object_text(object)
        image, result, started = self._start(image, "point", object)
        client = self._ensure_client(result)
        result["points"] = self._ground(client, image, object, result, "point")
        return self._finish(result, started)

    def segment(self, image, object, *, grounded_by="detect"):
        """Segment actual detected boxes or predicted positive points.

        Point prompts request multiple mask candidates; the adapter selects by
        its own predicted score. Neither mode chooses a mask by ground truth.
        """
        if grounded_by not in ("detect", "point"):
            raise ValueError("grounded_by must be 'detect' or 'point'")
        object = _object_text(object)
        image, result, started = self._start(image, "segment", object)
        result.update(objects=[], segmenter_name=self.segmenter_name,
                      grounded_by=grounded_by,
                      presence_mode=self.presence_mode, presence=None,
                      raw_grounding=None, segmenter_used=False)
        client = self._ensure_client(result)
        if self.presence_mode == "query":
            question = f"Is there at least one {object} visible in this image? Answer only yes or no."
            raw = self._timed(result, "presence", lambda: client.query(
                image, question, settings={"max_tokens": 8}))
            decision = _presence_answer(raw)
            result["presence"] = {"question": question, "raw_response": copy.deepcopy(raw),
                                  "decision": decision}
            if decision is not True:
                result["status"] = "presence_rejected" if decision is False else "presence_unrecognized"
                return self._finish(result, started)
        objects = self._ground(client, image, object, result, grounded_by)
        if not objects:
            return self._finish(result, started)
        if self._segmenter is None:
            self._segmenter = self._timed(result, "segmenter_load", lambda: self._segmenter_loader(
                self.segmenter_name, device=self.device, state_dir=self.segmenter_state_dir))
        result["segmenter_receipt"] = copy.deepcopy(self._segmenter.receipt)
        result["image_encoding"] = self._timed(result, "image_encode", lambda: self._segmenter.set_image(image))
        result["segmenter_used"] = True
        for grounded in objects:
            prompt = ({"box": grounded["box"], "multimask": False}
                      if grounded_by == "detect" else
                      {"points": [grounded["point"]], "labels": [1], "multimask": True})
            predicted = self._timed(result, "mask_decode", lambda: self._segmenter.predict(**prompt))
            result["objects"].append({**grounded, "mask": predicted["mask"],
                                      "mask_metadata": {k: v for k, v in predicted.items() if k != "mask"}})
        return self._finish(result, started)
