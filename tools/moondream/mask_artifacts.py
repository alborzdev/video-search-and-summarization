"""Render Moondream segmentation evidence without model or GPU dependencies.

Moondream paths use normalized coordinates RELATIVE TO THE RETURNED BBOX.
See https://docs.moondream.ai/skills/segment/#using-the-svg-path and installed
kestrel/seg_refiner.py:svg_from_path. Bounding boxes alone are not masks.

The existing system librsvg/Cairo renderer parses a generated path-only SVG.
Only a validated SVG path-data string is accepted, never caller-supplied XML,
scripts, styles, URLs, or external assets. No new packages are required.
"""

import io
import json
import math
from pathlib import Path
import re
import subprocess

from PIL import Image


_TOKEN = re.compile(r"[AaCcHhLlMmQqSsTtVvZz]|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6,
          "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
_RSVG_HELPER = """
import io, sys
import cairo
import gi
gi.require_version('Rsvg', '2.0')
from gi.repository import Rsvg
width, height = int(sys.argv[1]), int(sys.argv[2])
handle = Rsvg.Handle.new_from_data(sys.stdin.buffer.read())
surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
context = cairo.Context(surface)
viewport = Rsvg.Rectangle()
viewport.x = viewport.y = 0
viewport.width, viewport.height = width, height
if not handle.render_document(context, viewport):
    raise RuntimeError('librsvg did not render the mask')
output = io.BytesIO()
surface.write_to_png(output)
sys.stdout.buffer.write(output.getvalue())
"""


def _path_data(path):
    """Validate path syntax before passing canonical data to the SVG parser."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Missing SVG path")
    if len(path) > 200_000:
        raise ValueError("SVG path exceeds the evidence renderer's size limit")
    tokens, position = [], 0
    for match in _TOKEN.finditer(path):
        if path[position:match.start()].strip(" ,\t\r\n"):
            raise ValueError("SVG path contains unsupported characters")
        tokens.append(match.group())
        position = match.end()
    if path[position:].strip(" ,\t\r\n") or not tokens:
        raise ValueError("SVG path contains unsupported characters")
    if tokens[0] not in ("M", "m"):
        raise ValueError("SVG path must begin with a move command")
    index = 0
    while index < len(tokens):
        command = tokens[index]
        if command.upper() not in _ARITY:
            raise ValueError("Expected an SVG path command")
        index += 1
        numbers = []
        while index < len(tokens) and tokens[index].upper() not in _ARITY:
            value = float(tokens[index])
            if not math.isfinite(value) or abs(value) > 1_000_000:
                raise ValueError("SVG path has nonfinite or unbounded coordinates")
            numbers.append(value)
            index += 1
        arity = _ARITY[command.upper()]
        if (arity == 0 and numbers) or (arity and (not numbers or len(numbers) % arity)):
            raise ValueError("SVG path ends with an incomplete command")
        if command.upper() == "A":
            for offset in range(0, len(numbers), 7):
                if (numbers[offset] < 0 or numbers[offset + 1] < 0
                        or numbers[offset + 3] not in (0, 1)
                        or numbers[offset + 4] not in (0, 1)):
                    raise ValueError("Invalid SVG arc parameters")
    return " ".join(tokens)


def _bbox_values(bbox):
    if not isinstance(bbox, dict):
        raise ValueError("A bounding box is required to position the SVG path")
    values = []
    for key in ("x_min", "y_min", "x_max", "y_max"):
        value = bbox.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Bounding box coordinates must be numbers")
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Bounding box coordinates must be finite and normalized")
        values.append(value)
    x0, y0, x1, y1 = values
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Bounding box must have positive area")
    return x0, y0, x1 - x0, y1 - y0


def rasterize_mask(path, bbox, image_size):
    """Return a Pillow L mask and its safe full-image SVG source.

    Actual SVG curves, relative commands, arcs, holes and multiple contours
    are interpreted by librsvg. No polygon approximation is substituted.
    """
    width, height = image_size
    if (not isinstance(width, int) or not isinstance(height, int)
            or width <= 0 or height <= 0 or width * height > 16_000_000):
        raise ValueError("Evidence images must be positive and at most 16 megapixels")
    canonical = _path_data(path)
    x0, y0, sx, sy = _bbox_values(bbox)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           'viewBox="0 0 1 1" preserveAspectRatio="none">'
           f'<path d="{canonical}" fill="white" '
           f'transform="translate({x0} {y0}) scale({sx} {sy})"/></svg>')
    result = subprocess.run(
        ['/usr/bin/python3', '-I', '-c', _RSVG_HELPER, str(width), str(height)],
        input=svg.encode('ascii'), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=10, check=False)
    if result.returncode:
        raise RuntimeError("System librsvg renderer failed: "
                           + result.stderr.decode('utf-8', errors='replace')[-1000:])
    raster = Image.open(io.BytesIO(result.stdout)).convert('RGBA')
    if raster.size != image_size:
        raise RuntimeError("SVG raster size differs from the source image")
    return raster.getchannel('A'), svg


def save_mask_artifacts(image, result, output_dir, stem='segment'):
    """Save mask, overlay and metadata; explicitly classify unusable results.

    ``valid_mask`` means a renderable mask with nonzero area that does not
    cover the entire frame. It does not certify object/inspection accuracy.
    Empty/full-frame masks are retained as evidence but never marked valid.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]+', stem):
        raise ValueError("Artifact stem must be a simple filename")
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    source = image.convert('RGBA')
    record = {'valid_mask': False, 'quality_validated': False,
              'image_size': list(source.size), 'coordinate_system': 'bbox_relative_0_1',
              'renderer': 'system_librsvg', 'bbox': result.get('bbox'), 'artifacts': {}}
    path = result.get('path')
    if not isinstance(path, str) or not path.strip():
        record['status'] = 'bbox_only' if result.get('bbox') else 'empty_result'
    else:
        try:
            mask, svg = rasterize_mask(path, result.get('bbox'), source.size)
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            record.update(status='invalid_mask', error=str(exc))
        else:
            histogram = mask.histogram()
            total_pixels = source.width * source.height
            nonzero_pixels = total_pixels - histogram[0]
            record.update(nonzero_pixels=nonzero_pixels,
                          mask_fraction=nonzero_pixels / total_pixels,
                          alpha_weighted_fraction=sum(i * n for i, n in enumerate(histogram))
                          / (255 * total_pixels),
                          raster_bbox=list(mask.getbbox()) if mask.getbbox() else None)
            if not nonzero_pixels:
                record['status'] = 'zero_area_mask'
            elif nonzero_pixels == total_pixels:
                record['status'] = 'full_frame_mask'
            else:
                record.update(status='nonempty_mask', valid_mask=True)
            mask_file = directory / f'{stem}.mask.png'
            svg_file = directory / f'{stem}.mask.svg'
            overlay_file = directory / f'{stem}.overlay.png'
            mask.save(mask_file)
            svg_file.write_text(svg, encoding='ascii')
            tint = Image.new('RGBA', source.size, (0, 211, 190, 0))
            tint.putalpha(mask.point(lambda value: round(value * .38)))
            Image.alpha_composite(source, tint).convert('RGB').save(overlay_file)
            record['artifacts'].update(mask=str(mask_file), svg=str(svg_file),
                                       overlay=str(overlay_file))
    metadata_file = directory / f'{stem}.mask.json'
    record['artifacts']['metadata'] = str(metadata_file)
    metadata_file.write_text(json.dumps(record, indent=2) + '\n')
    return record
