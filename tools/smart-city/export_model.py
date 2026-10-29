#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export a pinned RF-DETR checkpoint in an isolated PyTorch environment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", choices=("small", "medium", "large"), default="small")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    if importlib.metadata.version("rfdetr") != "1.11.2":
        raise RuntimeError("This export requires the reviewed rfdetr==1.11.2")

    import onnx
    import torch
    from rfdetr import RFDETRLarge, RFDETRMedium, RFDETRSmall

    torch.set_num_threads(4)
    args.output.mkdir(parents=True, exist_ok=True)
    model_type = {"small": RFDETRSmall, "medium": RFDETRMedium, "large": RFDETRLarge}[args.size]
    model = model_type(pretrain_weights=str(args.checkpoint), device="cpu")
    result = model.export(
        output_dir=str(args.output), format="onnx", opset_version=17,
        batch_size=args.batch, dynamic_batch=True, fp16=False,
    )
    path = Path(result)
    graph = onnx.load(str(path))
    onnx.checker.check_model(graph)
    inputs = {v.name: onnx.TensorProto.DataType.Name(v.type.tensor_type.elem_type) for v in graph.graph.input}
    outputs = {v.name: onnx.TensorProto.DataType.Name(v.type.tensor_type.elem_type) for v in graph.graph.output}
    if set(outputs) != {"dets", "labels"} or any(v != "FLOAT" for v in outputs.values()):
        raise RuntimeError(f"Unexpected native parser output contract: {outputs}")
    if any(v != "FLOAT" for v in inputs.values()):
        raise RuntimeError(f"Expected FP32 input tensor: {inputs}")
    receipt = {
        "model": args.size, "checkpointSha256": sha256(args.checkpoint),
        "onnx": str(path), "onnxSha256": sha256(path), "opset": 17,
        "spatialResolution": {"small": 512, "medium": 576, "large": 704}[args.size],
        "dynamicBatch": True, "optimizationBatch": args.batch,
        "inputs": inputs, "outputs": outputs,
        "normalization": {"mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]},
        "outputContract": {"dets": "normalized-cxcywh", "labels": "raw-sigmoid-logits-sparse-coco"},
        "versions": {name: importlib.metadata.version(name) for name in ("rfdetr", "torch", "torchvision", "onnx", "transformers")},
    }
    (args.output / "export-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
