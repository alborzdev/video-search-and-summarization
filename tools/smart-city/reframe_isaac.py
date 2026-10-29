#!/usr/bin/env python3
"""Migrate the existing city site and its rules to a reviewed camera export.

The caller must pause the owned detector and supply a saved site/rules backup.
No default rules or zones are created, and geometry is reprojected only when
camera geometry is known. Runtime source dimensions are updated after the
site and rules accept their revision-checked updates.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BASE = 'http://127.0.0.1:9184/api/v1/city/'
CONTROLLER = 'http://127.0.0.1:9190/api/v1/detections'


def request(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='GET' if data is None else 'PUT')
    with urllib.request.urlopen(req, timeout=15) as result:
        return json.load(result)


def invert3(m):
    a,b,c=m[0]; d,e,f=m[1]; g,h,i=m[2]
    det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
    if abs(det) < 1e-15: raise ValueError('Singular camera homography')
    return [[v/det for v in row] for row in [[e*i-f*h,c*h-b*i,b*f-c*e],[f*g-d*i,a*i-c*g,c*d-a*f],[d*h-e*g,b*g-a*h,a*e-b*d]]]


def project(m, x, y):
    q=[row[0]*x+row[1]*y+row[2] for row in m]
    if q[2] <= 1e-10: raise ValueError('Rule is behind the new camera or horizon')
    return q[0]/q[2], q[1]/q[2]


def image_geometry(geometry, old, new):
    """Reproject image rules through the old and new ground-plane cameras."""
    geom = copy.deepcopy(geometry)
    if geom.get('space') != 'image-normalized': return geom
    matrix = invert3(new['imageToGroundHomography'])
    def convert(point):
        world=project(old['imageToGroundHomography'], point[0]*old['width'], point[1]*old['height'])
        pixel=project(matrix, *world)
        return [pixel[0]/new['width'], pixel[1]/new['height']]
    points=geom['points']
    geom['points']=[convert(p) for p in points]
    if any(not -1e-7 <= value <= 1+1e-7 for point in geom['points'] for value in point):
        raise ValueError('Existing rule falls outside the new camera frame')
    if geom.get('direction') is not None:
        center=[sum(p[i] for p in points)/len(points) for i in (0,1)]
        moved=[center[i]+geom['direction'][i] for i in (0,1)]
        a,b=convert(center),convert(moved)
        geom['direction']=[b[i]-a[i] for i in (0,1)]
    return geom


def build(site, rules, old_export, new_export, registration):
    if site['id'] != 'isaac-intersection-a' or old_export['cameraOrder'] != new_export['cameraOrder']:
        raise ValueError('Unexpected site or camera identities')
    oldrev, newrev = old_export['calibrationRevision'], new_export['calibrationRevision']
    by_id = {}
    new_site = copy.deepcopy(site)
    for name in new_export['cameraOrder']:
        camera_id = registration[name]['id']
        source = next(item for item in new_site['sources'] if item['id'] == camera_id)
        old, new = old_export['cameras'][name], new_export['cameras'][name]
        if source.get('calibrationRevision') != oldrev or [source['width'], source['height']] != [old['width'], old['height']]:
            raise ValueError('The saved camera calibration does not match the current site')
        if any(not math.isclose(source['T_cv_from_site'][i][j], old['T_cv_from_site'][i][j], abs_tol=1e-6)
               for i in range(4) for j in range(4)):
            raise ValueError('The saved camera pose does not match the current site')
        source.update(new)
        source['calibrationRevision'] = newrev
        source.pop('processedPreview', None)
        by_id[camera_id] = (old, new)
    if len(by_id) != len(new_site['sources']):
        raise ValueError('Unexpected sources in city site')
    new_site['expectedRevision'] = site['revision']
    new_site['revision'] = site['revision'] + 1
    new_rules = copy.deepcopy(rules['rules'])
    for rule in new_rules:
        if rule['sourceId'] not in by_id:
            raise ValueError('Rule belongs to an unexpected source')
        rule['geometry'] = image_geometry(rule['geometry'], *by_id[rule['sourceId']])
        if rule.get('calibrationRevision') is not None:
            if rule['calibrationRevision'] != oldrev:
                raise ValueError('Rule has a different calibration revision')
            rule['calibrationRevision'] = newrev
    return new_site, new_rules, by_id


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2)
            out.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text())
    site, rules = read(args.backup / 'site.json'), read(args.backup / 'rules.json')
    old, new = read(args.backup / 'calibration.json'), read(args.export)
    registrations = read(ROOT / '.spark/city/isaac-registration.json')
    new_site, new_rules, by_id = build(site, rules, old, new, registrations)
    result = {'resolution': [new['cameras'][new['cameraOrder'][0]]['width'], new['cameras'][new['cameraOrder'][0]]['height']],
              'ruleIds': [r['id'] for r in new_rules], 'calibrationRevision': new['calibrationRevision'], 'applied': False}
    if args.apply:
        if request(CONTROLLER)['state'] != 'paused':
            raise RuntimeError('Pause detections before changing camera calibration')
        current_site, current_rules = request(BASE+'site'), request(BASE+'rules')
        if current_site['revision'] != site['revision'] or current_rules['revision'] != rules['revision']:
            raise RuntimeError('Site or rules changed since backup; review them before migration')
        request(BASE+'site', new_site)
        after_rules = request(BASE+'rules')
        request(BASE+'rules', {'expectedRevision': after_rules['revision'], 'rules': new_rules})
        source_path = ROOT / '.spark/city/controller-sources.json'
        sources = read(source_path)
        if set(by_id) - set(sources): raise RuntimeError('Controller source archive changed')
        for key, (_, camera) in by_id.items():
            sources[key]['width'], sources[key]['height'] = camera['width'], camera['height']
        atomic_json(source_path, sources)
        result['applied'] = True
    print(json.dumps(result))


if __name__ == '__main__': main()
