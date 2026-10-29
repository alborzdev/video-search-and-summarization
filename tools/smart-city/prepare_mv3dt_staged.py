#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare, never activate, a hash-pinned local-NvDCF then MV3DT candidate."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import yaml

import isaac_identical_calibration as calibration
import mv3dt_demo_profile as demo
import prepare_mv3dt_stable_ids as baseline

ARCHITECTURE = 'nvdcf-local-then-mv3dt-v1'
LOCAL_NAME = 'tracker-nvdcf-local.yml'


def prepare(root: Path, snapshot: str, image_id: str, local_config: Path) -> dict:
    require = calibration.require
    require(calibration.NAME.fullmatch(snapshot), 'Expected a unique plain snapshot name')
    require(demo.IMAGE.fullmatch(image_id), 'Expected an immutable native image ID')
    state = root / '.spark/city/state'
    active = state / baseline.PREFIX / 'active.json'
    rollback = active.read_bytes()
    profile = demo.load(root, 'spark')
    if profile is None:
        raise ValueError('An enabled pinned parent profile is required')
    require(profile.get('trackingArchitecture') is None, 'Expected a single-stage parent profile')
    old = profile['trackerConfig'].rsplit('/', 1)[0] + '/'
    new = baseline.PREFIX + snapshot + '/'
    require(old != new and not (state / new).exists(), 'Candidate snapshot already exists')
    require(set(profile['fileHashes']) == {old + name for name in baseline.FILES},
            'Expected exactly seven supported parent pins')
    require(local_config.is_file() and not local_config.is_symlink()
            and local_config.stat().st_size <= 262144, 'Expected a bounded ordinary local tracker config')
    local_bytes = local_config.read_bytes()
    local = yaml.safe_load(local_bytes)
    require(isinstance(local, dict)
            and local.get('BaseConfig', {}).get('checkClassMatch') == 1
            and local.get('StateEstimator', {}).get('stateEstimatorType') == 1
            and local.get('VisualTracker', {}).get('visualTrackerType') == 2
            and local.get('ReID', {}).get('reidType') == 0
            and local.get('TrajectoryManagement', {}).get('useUniqueID') == 1
            and local.get('TrajectoryManagement', {}).get('enableReAssoc') == 0,
            'Local config must be ordinary class-matched unique-ID 2D NvDCF without ReID/reassociation')
    require(not any(key in local for key in ('MultiViewAssociator', 'ObjectModelProjection', 'Communicator')),
            'Local stage must not enable multiview or projection metadata')
    files = {name: (state / old / name).read_bytes() for name in baseline.FILES}
    export_path = state / old / 'current-static-export.json'
    export_bytes = export_path.read_bytes()
    export, package = json.loads(export_bytes), json.loads(files['package.json'])
    revision = set(profile['cameraCalibrations'].values())
    require(len(revision) == 1 and package.get('calibrationRevision') in revision
            and export.get('calibrationRevision') in revision,
            'Profile/package/static export calibration differs')
    require(package.get('siteId') == profile['siteId']
            and [camera['sourceId'] for camera in package.get('cameras', [])] == profile['cameraOrder'],
            'Package camera/site order differs')
    tracker = yaml.safe_load(files['tracker-mv3dt.experimental.yml'])
    original = deepcopy(tracker)
    assoc = tracker['MultiViewAssociator']
    require(assoc.get('multiViewAssociatorType') == 1 and assoc.get('enableSeeThrough') == 0,
            'Expected guarded native MV3DT baseline')
    changes = []
    for key in ('enableLatePeerReAssoc', 'enableIDCorrection'):
        require(type(assoc.get(key)) is int and assoc[key] in (0, 1), 'Expected explicit parent flag: ' + key)
        changes.append({'path': 'MultiViewAssociator.' + key, 'before': assoc[key], 'after': 1})
        assoc[key] = 1
    references = []

    def rebased(value):
        require(isinstance(value, str) and value.startswith('/state/' + old), 'Unpinned tracker reference')
        name = value[len('/state/' + old):]
        require(name in baseline.FILES and '/' not in name, 'Unpinned tracker file reference')
        references.append({'before': value, 'after': '/state/' + new + name})
        return '/state/' + new + name

    paths = tracker['ObjectModelProjection']['cameraModelFilepath']
    require(paths == ['/state/' + old + f'camera-{i}.yml' for i in range(2)], 'Tracker camera order differs')
    tracker['ObjectModelProjection']['cameraModelFilepath'] = [rebased(path) for path in paths]
    comm = tracker['Communicator']
    require(comm.get('communicatorType') == 2, 'Expected MQTT communicator')
    for key, name in (('pubSubInfoConfigPath', 'pub-sub.yml'), ('mqttProtoAdaptorConfigPath', 'mqtt.ini')):
        require(comm.get(key) == '/state/' + old + name, 'Unexpected communicator file reference')
        comm[key] = rebased(comm[key])
    restored = deepcopy(tracker)
    restored['MultiViewAssociator'] = original['MultiViewAssociator']
    restored['ObjectModelProjection']['cameraModelFilepath'] = paths
    restored['Communicator'] = original['Communicator']
    calibration.same(restored, original, 'Only the declared second-stage flags and paths may change')
    files['tracker-mv3dt.experimental.yml'] = yaml.safe_dump(tracker, sort_keys=False).encode()
    files[LOCAL_NAME] = local_bytes
    policy = {'schemaVersion': 'city.mv3dt-staged-policy.v1', 'name': ARCHITECTURE,
              'candidateOnly': True, 'runtimeQualified': False,
              'localIdentityAuthority': 'first-native-nvdcf-sdk-handle',
              'mapIdentityAuthority': 'second-native-mv3dt-sdk-handle',
              'associationJoin': 'exact-current-detector-object-user-meta',
              'noHeuristicAliases': True, 'noGroundTruthIdentity': True,
              'parentProfileSha256': calibration.sha(rollback), 'changes': changes,
              'rebasedFileReferences': references,
              'localConfigSourceSha256': calibration.sha(local_bytes), 'existingMapGuardsUnchanged': True}
    manifest = json.loads(files['manifest.json'])
    manifest.update(identityPolicyVariant=policy, runtimeQualified=False,
                    transportClockQualified=False, diagnosticOnly=True, enabled=False)
    files['manifest.json'] = calibration.encoded(manifest)
    candidate = deepcopy(profile)
    candidate.update(trackerConfig=new + 'tracker-mv3dt.experimental.yml',
                     localTrackerConfig=new + LOCAL_NAME, trackingArchitecture=ARCHITECTURE,
                     imageId=image_id, identityPolicyVariant=policy, productionQualified=False)
    candidate['fileHashes'] = {new + name: calibration.sha(data) for name, data in sorted(files.items())}
    require(len(candidate['fileHashes']) == 8, 'Expected all eight staged configuration pins')
    require(active.read_bytes() == rollback and demo.load(root, 'spark') == profile
            and local_config.read_bytes() == local_bytes and export_path.read_bytes() == export_bytes,
            'Parent inputs changed during preparation')
    return {'profile': candidate, 'rollback': rollback, 'files': files, 'export': export_bytes, 'prefix': new,
            'receipt': {'schemaVersion': 'city.mv3dt-staged-preparation.v1',
                        'preparedOnly': True, 'runtimeChanged': False, 'variant': ARCHITECTURE,
                        'sourceActiveProfile': str(active), 'sourceActiveSha256': calibration.sha(rollback),
                        'sourceFileHashes': profile['fileHashes'], 'staticExportSha256': calibration.sha(export_bytes),
                        'candidateProfileSha256': calibration.sha(calibration.encoded(candidate)),
                        'candidateFileHashes': candidate['fileHashes'], 'cameraCalibrations': candidate['cameraCalibrations'],
                        'imageId': image_id, 'policy': policy}}


def write_review(output: Path, result: dict) -> None:
    baseline.write_review(output, result)
    path = output / 'receipt.json'
    receipt = json.loads(path.read_bytes())
    receipt['generatorSha256'] = calibration.sha(Path(__file__).read_bytes())
    path.write_bytes(calibration.encoded(receipt))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--local-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root.resolve(), args.snapshot, args.image_id, args.local_config.resolve())
    write_review(args.output.resolve(), result)
    print(json.dumps({'output': str(args.output.resolve()), **result['receipt']}, indent=2))


if __name__ == '__main__':
    main()
