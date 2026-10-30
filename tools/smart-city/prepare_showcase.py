#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Three camera-framed booth scenes. Geometry comes only from static calibration.

Prepare prints the exact configuration; --apply saves a backup then uses revision
checks. Retire only the named legacy demo rules, preserving operator additions.
"""
import argparse
import json
from pathlib import Path
from isaac_site import invert3, project, request

LEGACY = {'cam_sw-northbound-line','cam_sw-blocked-crossing','cam_ne-blocked-crossing',
    *('mobility-isaac-'+name for name in ('north-exit','west-exit','east-exit','east-right-exit',
       'northbound-queue','south-waiting-west','south-waiting-east','south-crossing-measurement',
       'east-waiting-south','east-waiting-north','east-crossing-measurement','north-curbside-lane'))}
REFERENCES = {'movements':('entryRuleId','exitRuleId'),'crossings':('waitingRuleId','crossingRuleId'),
              'queues':('zoneRuleId',),'curbs':('zoneRuleId',)}


def build(package, site, saved, mobility):
    if site['id'] != 'isaac-intersection-a' or package.get('cameraOrder') != ['cam_SW','cam_NE']:
        raise ValueError('The two current intersection cameras are required')
    sources = {key:next(item for item in site['sources'] if item['name']=='isaac-intersection-'+name)
               for key,name in [('cam_SW','southwest'),('cam_NE','northeast')]}
    if any(s.get('calibrationRevision') != package['calibrationRevision'] for s in site['sources']):
        raise ValueError('Camera calibration has changed; export and review it before applying')
    previous = {r['id']:r for r in saved['rules']}
    # Reviewed against the orthographic map and both unchanged live cameras.
    # XW_E's navigation survey extends beyond the visible paint. This polygon
    # follows the actual stripe edges, including the slight road skew.
    crossing = [[-11.157913810431364, 72.35760559271463], [-13.843809477679917, 73.3515576727803], [-13.638742309886563, 82.31474010901458], [-10.781761392571232, 82.47821290960839]]
    # Emergency access watches the NS cross-traffic corridor. The waiting
    # ambulance is outside this area and must not create its own blockage.
    zones = [('expo-crossing-occupancy','East crossing','occupancy-threshold',['person'],crossing,100),
        ('expo-approach-queue','North approach queue','queue',['car','bus','truck'],[[-27.2,93],[-23.7,93],[-23.8,103],[-27.3,103]],1500),
        ('expo-junction-blockage','Junction box','stopped-in-zone',['car','bus','truck'],[[-15.812755478602723, 72.88627102187658], [-29.616015016816625, 72.04166421443422], [-32.27617749927033, 74.61156020016918], [-31.365279711778086, 84.47251946913023], [-29.2429091498398, 85.94778987678153], [-16.454027191096046, 84.70315785368591], [-14.535009715671384, 82.84925782345162]],1800),
        ('expo-emergency-blockage','Emergency access','stopped-in-zone',['car','bus','truck'],[[-19.2, 72.67900912309653], [-28.4, 72.1160708832585], [-28.4, 85.0], [-19.5041489131365, 85.0], [-19.2, 84.97039979895814]],1800)]
    generated=[]
    for identifier,name,kind,classes,points,duration in zones:
        key = 'cam_NE' if classes == ['person'] else 'cam_SW'
        camera,source = package['cameras'][key],sources[key]
        # An image ROI marks road paint, so use the road plane consistently
        # with map and secondary-camera reprojection. Person foot calibration
        # belongs to track projection, not to the painted surface.
        h=camera['imageToGroundHomography']
        inverse=invert3(h); image=[]
        for p in points:
            u,v=project(inverse,p); image.append([u/camera['width'],v/camera['height']])
        if not all(0<=n<=1 for p in image for n in p):
            raise ValueError(name+' does not fit the current owner camera')
        generated.append({'id':identifier,'name':name,'kind':kind,'sourceId':source['id'],'classes':classes,
            'geometry':{'space':'image-normalized','points':image},'enabled':True,
            'revision':previous.get(identifier,{}).get('revision',0)+1,
            'conditions':{'countThreshold':2 if kind=='queue' else 1,'minimumDurationMs':duration,
                'speedBelowMps':.6,'clearAfterMs':400,'maximumObservationGapMs':750},
            'calibrationRevision':package['calibrationRevision']})
    ids={r['id'] for r in generated}
    rules=[r for r in saved['rules'] if r['id'] not in LEGACY|ids]+generated
    config={kind:[row for row in mobility.get(kind,[]) if not any(row[f] in LEGACY for f in refs)]
            for kind,refs in REFERENCES.items()}
    return rules,config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera-package',type=Path,default=Path('/home/sparkdev/Documents/ChatGPT/isaacsim-6/environments/city/logs/vss-integration/camera-map-export.json'))
    parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    package=json.loads(args.camera_package.read_text());site=request('site');saved=request('rules');mobility=request('mobility')['config']
    rules,config=build(package,site,saved,mobility)
    if not args.apply:
        print(json.dumps({'rules':rules,'mobility':config},indent=2));return
    backup=Path('.spark/city/runtime/showcase-20261029');backup.mkdir(parents=True,exist_ok=True)
    receipt=backup/'before.json'
    if not receipt.exists():receipt.write_text(json.dumps({'site':site,'rules':saved,'mobility':mobility},indent=2))
    # Remove only retired references before removing their rules.
    request('mobility/config',{**config,'expectedRevision':mobility['revision']})
    result=request('rules',{'rules':rules,'expectedRevision':saved['revision']})
    print(json.dumps({'revision':result['revision'],'areas':[r['name'] for r in rules],'backup':str(receipt)}))

if __name__=='__main__':main()
