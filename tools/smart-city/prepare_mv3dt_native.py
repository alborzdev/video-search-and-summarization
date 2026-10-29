#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare one native MV3DT tracker, with no separate local tracker or 2D fallback.

Clones the calibrated active bundle into a new review directory. Never applies
it or starts services. NVIDIA's reference MV3DT retains its internal CUDA DCF
module; this removes the application's extra NvDCF pipeline stage.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import yaml

import isaac_identical_calibration as calibration
import mv3dt_demo_profile as demo
import prepare_mv3dt_stable_ids as baseline


def prepare(root: Path, snapshot: str, image_id: str, *, two_wheeler: bool = False) -> dict:
    require = calibration.require
    require(calibration.NAME.fullmatch(snapshot), 'Expected a unique plain snapshot name')
    require(demo.IMAGE.fullmatch(image_id), 'Pinned worker image ID required')
    state = root / '.spark/city/state'
    active = state / baseline.PREFIX / 'active.json'
    rollback = active.read_bytes()
    profile = demo.load(root, 'spark')
    require(profile is not None, 'Enabled hash-pinned MV3DT profile required')
    old = profile['trackerConfig'].rsplit('/', 1)[0] + '/'
    new = baseline.PREFIX + snapshot + '/'
    require(old != new and not (state / new).exists(), 'Snapshot already exists')
    require({old + name for name in baseline.FILES} <= set(profile['fileHashes']),
            'Missing calibrated bundle pins')
    files = {name: (state / old / name).read_bytes() for name in baseline.FILES}
    export_bytes = (state / old / 'current-static-export.json').read_bytes()
    export, package = json.loads(export_bytes), json.loads(files['package.json'])
    revisions = set(profile['cameraCalibrations'].values())
    require(len(revisions) == 1 and package.get('calibrationRevision') in revisions
            and export.get('calibrationRevision') in revisions, 'Calibration revisions differ')
    require(package.get('siteId') == profile['siteId']
            and [c['sourceId'] for c in package['cameras']] == profile['cameraOrder'],
            'Package camera/site order differs')
    tracker = yaml.safe_load(files['tracker-mv3dt.experimental.yml'])
    require(tracker['StateEstimator']['stateEstimatorType'] == 3
            and tracker['MultiViewAssociator']['multiViewAssociatorType'] == 1
            and tracker['Communicator']['communicatorType'] == 2
            and tracker['TrajectoryManagement']['useUniqueID'] == 0
            and tracker['BaseConfig']['checkClassMatch'] == 1,
            'Expected calibrated class-aware native MV3DT with MQTT/global IDs')
    require(tracker['VisualTracker']['visualTrackerType'] == 2
            and tracker['VisualTracker']['vpiBackend4DcfTracker'] == 1,
            'Preserve NVIDIA reference internal DCF on CUDA, never PVA')
    paths = tracker['ObjectModelProjection']['cameraModelFilepath']
    require(paths == ['/state/' + old + f'camera-{i}.yml' for i in range(2)],
            'Tracker calibration order differs')
    camera_class_sets = []
    generated_two_wheeler_prior = False
    for i in range(2):
        camera = yaml.safe_load(files[f'camera-{i}.yml'])
        class_ids = [m['classID'] for m in camera['modelInfo']]
        require(len(class_ids) == len(set(class_ids)) and set(class_ids) in (set(range(6)), set(range(7))),
                'The six detector classes and any two-wheeler need unique explicit 3D priors')
        if two_wheeler and 6 not in class_ids:
            # TrafficCamNet combines bicycles and motorcycles. This provisional
            # midpoint is a model prior, not a new calibrated measurement.
            models = {m['classID']: m for m in camera['modelInfo']}
            camera['modelInfo'].append(dict(classID=6,
                height=(models[1]['height'] + models[3]['height']) / 2,
                radius=(models[1]['radius'] + models[3]['radius']) / 2))
            files[f'camera-{i}.yml'] = yaml.safe_dump(camera, sort_keys=False).encode()
            generated_two_wheeler_prior = True
        camera_class_sets.append({m['classID'] for m in camera['modelInfo']})
    require(camera_class_sets[0] == camera_class_sets[1], 'Camera model classes differ')
    topics = yaml.safe_load(files['pub-sub.yml'])
    pubs, subs = topics['pubBrokerTopicStr'], topics['subPeerBrokerTopicStrs']
    require(len(pubs) == 2 and len(set(pubs)) == 2 and subs == [[pubs[1]], [pubs[0]]],
            'Expected reciprocal camera MQTT vision neighbors')
    comm = tracker['Communicator']
    for key, name in [('pubSubInfoConfigPath', 'pub-sub.yml'), ('mqttProtoAdaptorConfigPath', 'mqtt.ini')]:
        require(comm[key] == '/state/' + old + name, 'Unpinned communicator reference')
        comm[key] = '/state/' + new + name
    tracker['ObjectModelProjection']['cameraModelFilepath'] = ['/state/' + new + f'camera-{i}.yml' for i in range(2)]
    # Installed 9.2 requires TargetManagement.outputVisibility at runtime.
    # Retain it alongside the newer reference app's projection output flag.
    tracker['TargetManagement']['outputVisibility'] = 1
    tracker['ObjectModelProjection'].update(outputFootLocation=1, outputVisibility=1)
    tracker['BaseConfig']['useBatchNumForFrameId'] = 1
    tracker['MultiViewAssociator'].update(enableLatePeerReAssoc=1, enableIDCorrection=1, enableMsgSync=0)
    files['tracker-mv3dt.experimental.yml'] = yaml.safe_dump(tracker, sort_keys=False).encode()
    singles = {}
    for i, source in enumerate(profile['cameraOrder']):
        single = deepcopy(tracker)
        single['MultiViewAssociator']['enableMsgSync'] = 0  # no running peer during single-source admission
        single['ObjectModelProjection']['cameraModelFilepath'] = [tracker['ObjectModelProjection']['cameraModelFilepath'][i]]
        topic_name, tracker_name = f'pub-sub-single-{i}.yml', f'tracker-single-{i}.yml'
        single['Communicator']['pubSubInfoConfigPath'] = '/state/' + new + topic_name
        # Keep the camera's own publish identity and its actual vision neighbor.
        files[topic_name] = yaml.safe_dump(dict(pubBrokerTopicStr=[pubs[i]],
            subPeerBrokerTopicStrs=[subs[i]]), sort_keys=False).encode()
        files[tracker_name] = yaml.safe_dump(single, sort_keys=False).encode()
        singles[source] = new + tracker_name
    policy = dict(schemaVersion='city.mv3dt-native-policy.v1', name=demo.NATIVE,
        trackerStages=1, separateLocalTracker=False, internalVisualTracker='nvidia-reference-dcf-cuda',
        identityAuthority='native-mv3dt-sdk-target', mapPositionAuthority='native-mv3dt-world-foot',
        classes=['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck'],
        noHeuristicAliases=True, noGroundTruthIdentity=True,
        parentProfileSha256=calibration.sha(rollback), runtimeQualified=False)
    if 6 in camera_class_sets[0]:
        policy['classes'].append('two-wheeler')
        policy['twoWheeler3dPrior'] = ('provisional midpoint of existing bicycle and motorcycle priors; not calibrated'
            if generated_two_wheeler_prior else profile.get('identityPolicyVariant', {}).get('twoWheeler3dPrior',
                'inherited prior; calibration not verified by this preparation'))
    manifest = json.loads(files['manifest.json'])
    manifest.update(identityPolicyVariant=policy, runtimeQualified=False, enabled=False)
    files['manifest.json'] = calibration.encoded(manifest)
    candidate = deepcopy(profile)
    candidate.pop('localTrackerConfig', None)
    candidate.update(trackerConfig=new + 'tracker-mv3dt.experimental.yml', singleCameraTrackerConfigs=singles,
        trackingArchitecture=demo.NATIVE, imageId=image_id, identityPolicyVariant=policy, productionQualified=False)
    candidate['fileHashes'] = {new + name: calibration.sha(data) for name, data in sorted(files.items())}
    require(active.read_bytes() == rollback and demo.load(root, 'spark') == profile,
            'Active profile changed during preparation')
    return dict(profile=candidate, rollback=rollback, files=files, export=export_bytes, prefix=new,
        receipt=dict(schemaVersion='city.mv3dt-native-preparation.v1', preparedOnly=True, runtimeChanged=False,
            sourceActiveSha256=calibration.sha(rollback), sourceFileHashes=profile['fileHashes'],
            candidateProfileSha256=calibration.sha(calibration.encoded(candidate)),
            candidateFileHashes=candidate['fileHashes'], imageId=image_id, policy=policy))


def write_review(output: Path, result: dict) -> None:
    baseline.write_review(output, result)
    path = output / 'receipt.json'
    receipt = json.loads(path.read_bytes())
    receipt['generatorSha256'] = calibration.sha(Path(__file__).read_bytes())
    path.write_bytes(calibration.encoded(receipt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--two-wheeler', action='store_true',
                        help='add a provisional combined two-wheeler 3D prior for TrafficCamNet')
    args = parser.parse_args()
    result = prepare(args.root.resolve(), args.snapshot, args.image_id, two_wheeler=args.two_wheeler)
    write_review(args.output.resolve(), result)
    print(json.dumps({'output': str(args.output.resolve()), **result['receipt']}, indent=2))


if __name__ == '__main__':
    main()
