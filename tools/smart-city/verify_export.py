#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare exported RF-DETR against its reference using an actual video frame."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", choices=("small", "medium", "large"), default="small")
    args = parser.parse_args()
    import cv2
    import numpy as np
    import onnxruntime as ort
    import torch
    from rfdetr import RFDETRLarge, RFDETRMedium, RFDETRSmall
    from torchvision.transforms import functional as F

    torch.set_num_threads(4)
    cap = cv2.VideoCapture(str(args.video))
    ok, frame = cap.read()
    fps, frames = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if not ok:
        raise RuntimeError("Video positive control could not be decoded")
    args.output.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output / "positive-control.jpg"), frame)
    resolution = {"small": 512, "medium": 576, "large": 704}[args.size]
    image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    tensor = F.to_tensor(image)
    tensor = F.resize(tensor, [resolution, resolution], antialias=False)
    tensor = F.normalize(tensor, [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]).unsqueeze(0)
    model_type = {"small": RFDETRSmall, "medium": RFDETRMedium, "large": RFDETRLarge}[args.size]
    model = model_type(pretrain_weights=str(args.checkpoint), device="cpu")
    model.model.model.eval()
    with torch.no_grad():
        reference = model.model.model(tensor)
    reference_boxes = reference["pred_boxes"].numpy()
    reference_logits = reference["pred_logits"].numpy()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(args.onnx), sess_options=options, providers=["CPUExecutionProvider"])
    output_names = [output.name for output in session.get_outputs()]
    comparisons = []
    for batch in (1, 2):
        input_data = np.repeat(tensor.numpy(), batch, axis=0)
        started = time.perf_counter()
        values = dict(zip(output_names, session.run(None, {"input": input_data})))
        elapsed = time.perf_counter() - started
        errors = {}
        for name, expected in (("dets", reference_boxes), ("labels", reference_logits)):
            expected = np.repeat(expected, batch, axis=0)
            errors[name] = float(np.max(np.abs(values[name] - expected)))
            np.testing.assert_allclose(values[name], expected, atol=0.002, rtol=0.001)
        comparisons.append({"batch": batch, "seconds": elapsed, "maxAbsoluteError": errors})
    logits = reference_logits[0]
    probabilities = torch.from_numpy(logits).sigmoid().numpy()
    indices = np.argsort(probabilities.ravel())[-300:][::-1]
    classes = indices % probabilities.shape[-1]
    scores = probabilities.ravel()[indices]
    selected = (scores >= 0.35) & np.isin(classes, [1, 2, 3, 4, 6, 8])
    detections = [{"cocoSlot": int(c), "confidence": float(s)} for c, s in zip(classes[selected], scores[selected])]
    if not detections:
        raise RuntimeError("Actual traffic positive control produced no road-user detections")
    np.savez_compressed(args.output / "golden.npz", input=tensor.numpy(), dets=reference_boxes, labels=reference_logits)
    receipt = {"video": str(args.video), "width": frame.shape[1], "height": frame.shape[0], "fps": fps,
               "frameCount": frames, "positiveDetections": detections, "comparisons": comparisons,
               "scope": "Reference-to-ONNX parity on one real traffic frame, batches one and two; not dataset accuracy"}
    (args.output / "parity-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
