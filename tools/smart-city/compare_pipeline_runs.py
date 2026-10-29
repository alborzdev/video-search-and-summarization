#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare exact recorded frames. Baseline agreement is NOT ground-truth accuracy."""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def frame_key(row):
    return row['sourceId'], row['sourceFrameId'], row['rawSourcePtsNs']


def load(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    result = {frame_key(row): row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate source frame/PTS records')
    return result


def iou(a, b):
    x, y, w, h = a
    u, v, s, t = b
    intersection = max(0, min(x+w, u+s)-max(x, u)) * max(0, min(y+h, v+t)-max(y, v))
    return intersection / (w*h+s*t-intersection) if intersection else 0


def matched_boxes(reference, candidate):
    # Explicit deterministic greedy matching, not identity ground truth.
    edges = sorted(((-iou(a['bboxPx'], b['bboxPx']), i, j)
                    for i, a in enumerate(reference) for j, b in enumerate(candidate)
                    if iou(a['bboxPx'], b['bboxPx']) >= .5))
    left, right, pairs = set(), set(), []
    for score, i, j in edges:
        if i not in left and j not in right:
            pairs.append((i, j, -score));left.add(i);right.add(j)
    return pairs


def percentile(values, fraction):
    return sorted(values)[min(len(values)-1, int((len(values)-1)*fraction))] if values else None


def compare(reference, candidate):
    common = sorted(reference.keys() & candidate.keys(), key=lambda k: (k[0], int(k[2])))
    if not common:
        raise ValueError('No exact source-frame/PTS overlap')
    counts, matches = Counter(), Counter()
    overlaps, displacement = [], []
    first_seen, first_matched, pair_history = {}, {}, {}
    id_changes = 0
    frames = []
    for key in common:
        a, b = reference[key], candidate[key]
        if a['image'] != b['image']:
            raise ValueError('Frame geometry mismatch')
        frames.append(b)
        left, right = a['objects'], b['objects']
        counts['referenceObjects'] += len(left);counts['candidateObjects'] += len(right)
        for obj in left:
            counts[obj['class']] += 1
            counts['smallObjects'] += obj['bboxPx'][3] < 40
            first_seen.setdefault((key[0], obj['localTrackId']), int(key[2]))
        for i, j, overlap in matched_boxes(left, right):
            ref, cand = left[i], right[j]
            matches['all'] += 1;matches[ref['class']] += 1
            matches['smallObjects'] += ref['bboxPx'][3] < 40
            matches['classDisagreements'] += ref['class'] != cand['class']
            overlaps.append(overlap)
            displacement.append(sum((ref['bboxPx'][n]+ref['bboxPx'][n+2]/2
                                     -cand['bboxPx'][n]-cand['bboxPx'][n+2]/2)**2 for n in (0, 1))**.5)
            first_matched.setdefault((key[0], ref['localTrackId']), int(key[2]))
            identity = (key[0], cand['localTrackId'])
            previous = pair_history.get(identity)
            if previous and previous[0] != ref['localTrackId'] and int(key[2])-previous[1] <= 250_000_000:
                id_changes += 1
            pair_history[identity] = (ref['localTrackId'], int(key[2]))
    timings = defaultdict(list)
    for row in frames:
        for name, value in row.get('pipelineTiming', {}).items():
            if name.endswith('Ms'):
                timings[name].append(value)
    delays = [(first_matched[key]-pts)/1e6 for key, pts in first_seen.items() if key in first_matched]
    return {
        'scope': 'Exact-frame baseline agreement; not labeled recall, precision, IDF1 or physical ID switches.',
        'commonFrames': len(common), 'referenceOnlyFrames': len(reference)-len(common),
        'candidateOnlyFrames': len(candidate)-len(common),
        'inferredFrames': sum(row.get('detectorRan') is True for row in frames),
        'trackerOnlyFrames': sum(row.get('detectorRan') is False for row in frames),
        'batchOccupancyByFrame': dict(Counter(row.get('pipelineTiming', {}).get('batchSize') for row in frames)),
        'counts': dict(counts), 'matches': dict(matches),
        'baselineBoxAgreement': matches['all']/counts['referenceObjects'] if counts['referenceObjects'] else None,
        'smallBaselineBoxAgreement': matches['smallObjects']/counts['smallObjects'] if counts['smallObjects'] else None,
        'meanMatchedIoU': statistics.mean(overlaps) if overlaps else None,
        'centerDisplacementPxP95': percentile(displacement, .95),
        'baselineIdentityPairChanges': id_changes,
        'baselineIdentitiesNeverMatched': len(first_seen)-len(first_matched),
        'firstBaselineIdentityMatchDelayMsP95': percentile(delays, .95),
        'timingMs': {name: {'median': statistics.median(values), 'p95': percentile(values, .95)}
                     for name, values in timings.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidates', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reference = load(args.baseline)
    args.output.write_text(json.dumps({str(path): compare(reference, load(path))
                                      for path in args.candidates}, indent=2)+'\n')


if __name__ == '__main__':
    main()
