"""Verify captured pixels and render lossless frame previews for manual review.

Usage: python3 inspect-live-input-capture.py CAPTURE_DIRECTORY
Does not classify frames or infer accuracy from successful generation.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def inspect(root):
    records = []
    for source in sorted(root.glob('*/input.json')):
        folder = source.parent
        metadata = json.loads(source.read_text())
        frames = np.load(folder / 'frames.npy', allow_pickle=False)
        digest = hashlib.sha256(frames.tobytes(order='C')).hexdigest()
        if digest != metadata['pixels_sha256']:
            raise ValueError(f'Pixel hash mismatch: {folder.name}')
        if list(frames.shape) != metadata['shape'] or str(frames.dtype) != metadata['dtype']:
            raise ValueError(f'Array metadata mismatch: {folder.name}')
        if frames.dtype != np.uint8 or frames.ndim != 4 or frames.shape[-1] not in (3, 4):
            raise ValueError(f'Unsupported frame format: {folder.name}')
        previews = []
        for index, frame in enumerate(frames):
            path = folder / f'frame-{index}.png'
            Image.fromarray(frame).save(path)
            previews.append(str(path.relative_to(root)))
        response_path = folder / 'response.json'
        response = json.loads(response_path.read_text()) if response_path.exists() else None
        if response and response['request_id'] != metadata['request_id']:
            raise ValueError(f'Response ID mismatch: {folder.name}')
        records.append({
            'request_id': metadata['request_id'],
            'captured_unix': metadata['captured_unix'],
            'shape': metadata['shape'],
            'pixels_sha256': digest,
            'frame_times': metadata.get('frame_times'),
            'video_metadata': metadata.get('video_metadata'),
            'chunk': metadata.get('chunk'),
            'sampling': metadata.get('sampling'),
            'capture_seconds': float((folder / 'capture-seconds.txt').read_text()),
            'outputs': response['outputs'] if response else None,
            'frames': previews,
            'manual_review': 'pending',
        })
    if not records:
        raise ValueError('No captured inputs found; do not infer that the trial passed')
    records.sort(key=lambda record: record['captured_unix'])
    (root / 'review-index.json').write_text(json.dumps(records, indent=2))
    print(json.dumps({'captured_requests': len(records),
                      'responses': sum(record['outputs'] is not None for record in records),
                      'max_capture_seconds': max(record['capture_seconds'] for record in records),
                      'review': str(root / 'review-index.json')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    inspect(parser.parse_args().directory)
