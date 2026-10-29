# SPDX-License-Identifier: Apache-2.0
"""Reproduce the bounded, offline person-anchor audit; no service requests."""
import bisect
import hashlib
import json
import math
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root / 'tools/smart-city'))
sys.path.insert(0, str(root / 'services/analytics/behavior-analytics'))
from apps.city.geometry import project
from evaluate_mv3dt_probe import assignment, percentile

inputs = {
    'observations': root / '.spark/city/runtime/isaac-ground-association-20261023/observations.ndjson',
    'package': root / '.spark/city/state/native/mv3dt-person-plane/package.json',
    'evaluationLabels': Path('/home/sparkdev/isaac_city_sim/logs/vss-integration/evaluation-ground-truth-1792730895658285642.ndjson'),
}
package = json.loads(inputs['package'].read_text())
cameras = {camera['sourceId']: camera for camera in package['cameras']}
rows = [json.loads(line) for line in inputs['observations'].read_text().splitlines()]
labels = [json.loads(line) for line in inputs['evaluationLabels'].read_text().splitlines()]
assert labels.pop(0)['kind'] == 'simulator-ground-truth-evaluation-only'
times = [int(row['captureUnixNs']) for row in labels]
assert times == sorted(set(times))
first = min(int(row['sourceTimeNs']) for row in rows if row['timestampBasis'] == 'source-rtcp')
by_camera = {source: {'positionErrors': [], 'speedErrors': [], 'estimatedSpeeds': [], 'trueSpeeds': [], 'projectionDeltas': []} for source in cameras}
previous = {}
for row in rows:
    ns = int(row['sourceTimeNs'])
    if row['timestampBasis'] != 'source-rtcp' or ns - first < 10e9:
        continue
    index = bisect.bisect_left(times, ns)
    candidates = [i for i in (index - 1, index) if 0 <= i < len(times)]
    index = min(candidates, key=lambda i: abs(times[i] - ns))
    if abs(times[index] - ns) > 250_000_000:
        continue
    camera = cameras[row['sourceId']]
    stats = by_camera[row['sourceId']]
    targets = []
    for name, world in labels[index]['peopleWorldM'].items():
        point = [world[0], world[1], world[2] - package['groundWorldZM'], 1.]
        pixel = [sum(a*b for a,b in zip(line, point)) for line in camera['projectionMatrix3x4']]
        if pixel[2] <= 0:
            continue
        pixel = [pixel[0] / pixel[2], pixel[1] / pixel[2]]
        if 0 <= pixel[0] <= camera['width'] and 0 <= pixel[1] <= camera['height']:
            targets.append((name, world[:2], pixel))
    detections = []
    for obj in row['objects']:
        if obj['class'] != 'person' or not obj['observedThisFrame'] or (obj.get('confidence') or 0) < .55:
            continue
        x, y, w, h = obj['bboxPx']
        anchor = [x+w/2, y+h]
        position, _ = project(anchor, camera['imageToGroundHomography'], camera.get('validGroundPolygon'), package.get('mapBoundsM'))
        if position is None:
            continue
        old_h = [r[0]*anchor[0]+r[1]*anchor[1]+r[2] for r in camera['imageToGroundHomography']]
        old_position = [old_h[0]/old_h[2], old_h[1]/old_h[2]]
        stats['projectionDeltas'].append(math.dist(position, old_position))
        detections.append((obj, position))
    costs = []
    for obj, position in detections:
        x,y,w,h = obj['bboxPx']
        costs.append([math.hypot((pixel[0]-x-w/2)/max(w,10), (pixel[1]-y-h)/max(h,20)) for _,_,pixel in targets])
    for oi, li in assignment(costs):
        obj, position = detections[oi]
        name, world, _ = targets[li]
        stats['positionErrors'].append(math.dist(position, world))
        identity = (row['sourceId'], row['sourceSessionId'], obj['localTrackId'])
        prior = previous.get(identity)
        if prior:
            dt = (ns-prior['ns'])/1e9
            truth_dt = (times[index]-prior['labelNs'])/1e9
            if 0 < dt <= .3 and 0 < truth_dt <= .3 and prior['name'] == name and int(row['sequence']) == prior['sequence'] + 1:
                speed = math.dist(position, prior['position'])/dt
                true_speed = math.dist(world, prior['world'])/truth_dt
                stats['speedErrors'].append(abs(speed-true_speed))
                stats['estimatedSpeeds'].append(speed)
                stats['trueSpeeds'].append(true_speed)
        previous[identity] = {'ns':ns, 'labelNs':times[index], 'name':name, 'position':position, 'world':world, 'sequence':int(row['sequence'])}

output = {'kind':'offline-person-anchor-audit', 'observationFrames':len(rows),
          'labelAssignment':'Independent image-space one-to-one assignment, confidence >= 0.55, maximum normalized matching cost 1; ambiguous occlusion assignments are possible. Speed uses consecutive source frames with the same local ID and matched person, 0 < frame and label intervals <= 0.3 seconds.',
          'qualification':'Saved simulator footage only. This is not a new runtime, detector-recall, speed-accuracy or fusion qualification. No smoothing, camera calibration, thresholds or operational actor inputs changed.',
          'inputs':{key:{'path':str(path), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for key,path in inputs.items()},
          'cameras':{source:{'matchedPersonSamples':len(stats['positionErrors']),
                            'positionMedianM':percentile(stats['positionErrors'], .5),
                            'positionP95M':percentile(stats['positionErrors'], .95),
                            'speedPairSamples':len(stats['speedErrors']),
                            'speedAbsoluteErrorMedianMps':percentile(stats['speedErrors'], .5),
                            'speedAbsoluteErrorP95Mps':percentile(stats['speedErrors'], .95),
                            'estimatedSpeedMedianMps':percentile(stats['estimatedSpeeds'], .5),
                            'trueSpeedMedianMps':percentile(stats['trueSpeeds'], .5),
                            'normalizedVsPriorProjectionMaximumDeltaM':max(stats['projectionDeltas'],default=None)} for source,stats in by_camera.items()}}
path = root / 'docs/qa/smart-city-2026-10-23/sprint-map-offline-audit.json'
path.write_text(json.dumps(output, indent=2)+'\n')
print(json.dumps(output, indent=2))
