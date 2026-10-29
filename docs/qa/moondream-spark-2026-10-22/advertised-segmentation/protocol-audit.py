"""CPU-only replay of saved segmentation tokens; never loads a model.

Run with .spark/moondream-photon/venv/bin/python from /home/sparkdev/vss.
This prints evidence JSON to stdout and writes no files by itself.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import sys

import numpy as np
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'tools/moondream'))
from mask_artifacts import rasterize_mask
from reference_decode import _svg_path

RUN = ROOT / 'docs/qa/moondream-spark-2026-10-22/non-photon/20261022T171044Z-preview-pytorch-reference'
SVG_SOURCE = ROOT / '.spark/moondream-photon/venv/lib/python3.12/site-packages/kestrel/utils/svg.py'
spec = importlib.util.spec_from_file_location('audited_upstream_svg', SVG_SOURCE)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)
tokenizer_path = Path((ROOT / '.spark/moondream-photon/tokenizer-path.txt').read_text().strip())
tokenizer = Tokenizer.from_file(str(tokenizer_path))
reports = [json.loads(line) for line in (RUN / 'inference.jsonl').read_text().splitlines()]
checks = []
for report in reports:
    result = report.get('result', {})
    if not result.get('path'):
        continue
    official_path, official_tokens = upstream.svg_path_from_token_ids(tokenizer, result['token_ids'])
    independent_path, independent_tokens = _svg_path(tokenizer, result['token_ids'])
    a_image, _ = rasterize_mask(official_path, result['bbox'], tuple(report['image_size']))
    b_image, _ = rasterize_mask(independent_path, result['bbox'], tuple(report['image_size']))
    a, b = np.asarray(a_image), np.asarray(b_image)
    aa, bb = a > 127, b > 127
    # Cubic control hull is a conservative bound, not a mask quality score.
    parts = re.findall(r'[A-Za-z]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?', independent_path)
    values = [float(p) for p in parts if p not in ('M', 'L', 'C', 'z', 'Z')]
    xs, ys = values[::2], values[1::2]
    checks.append({
        'case': report['case'],
        'decoded_token_lists_equal': official_tokens == independent_tokens,
        'saved_path_matches_independent_parser': result['path'] == independent_path,
        'official_raster_bbox': a_image.getbbox(),
        'independent_raster_bbox': b_image.getbbox(),
        'binary_iou_between_parsers': float((aa & bb).sum() / (aa | bb).sum()),
        'changed_binary_pixels': int((aa != bb).sum()),
        'max_alpha_difference': int(np.abs(a.astype(int) - b.astype(int)).max()),
        'path_control_hull_in_bbox_units': [min(xs), min(ys), max(xs), max(ys)],
        'model_bbox': result['bbox'],
        'bbox_was_clipped': result['bbox'] != result['unclipped_bbox'],
        'finish_reason': result['finish_reason'],
        'output_tokens': result['output_tokens'],
        'explicit_z_svg_end_eos': result['token_ids'][-3:] == [110, 11, 0],
        'note': 'Agreement between parsers is not agreement with ground truth.',
    })
paths = [SVG_SOURCE, ROOT / 'tools/moondream/reference_decode.py',
         ROOT / 'tools/moondream/mask_artifacts.py', RUN / 'inference.jsonl', tokenizer_path]
print(json.dumps({
    'audit_date': '2026-10-22',
    'mode': 'CPU-only saved-token replay; no model inference or service changes',
    'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    'checks': checks,
}, indent=2))
