#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare an isolated, hash-pinned MV3DT identity trial; never apply it.

This does not recover a hidden camera-local SDK ID. It disables only late
peer adoption and ID correction, so their effect can be measured explicitly.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import yaml

import isaac_identical_calibration as calibration
import mv3dt_demo_profile as demo

VARIANT = 'stable-local-ids-experimental'
PREFIX = 'native/mv3dt-demo/'
FILES = {'tracker-mv3dt.experimental.yml', 'camera-0.yml', 'camera-1.yml',
         'mqtt.ini', 'pub-sub.yml', 'package.json', 'manifest.json'}


def prepare(root: Path, snapshot: str) -> dict:
    """Return cloned bytes after validating the existing immutable profile."""
    require = calibration.require
    require(calibration.NAME.fullmatch(snapshot), 'Expected a unique plain snapshot name')
    state = root / '.spark/city/state'
    active = state / PREFIX / 'active.json'
    rollback = active.read_bytes()
    profile = demo.load(root, 'spark')
    require(profile is not None, 'An enabled hash-pinned MV3DT profile is required')
    old = profile['trackerConfig'].rsplit('/', 1)[0] + '/'
    new = PREFIX + snapshot + '/'
    require(old != new and not (state / new).exists(), 'Trial snapshot already exists')
    require(set(profile['fileHashes']) == {old + name for name in FILES},
            'Expected exactly the seven supported pinned configuration files')
    files = {name: (state / old / name).read_bytes() for name in FILES}
    export_path = state / old / 'current-static-export.json'
    export = calibration.read(export_path)
    export_bytes = export_path.read_bytes()
    package = json.loads(files['package.json'])
    revision = set(profile['cameraCalibrations'].values())
    require(len(revision) == 1 and package.get('calibrationRevision') in revision
            and export.get('calibrationRevision') in revision,
            'Profile/package/static export calibration differs')
    require(package.get('siteId') == profile['siteId']
            and [camera['sourceId'] for camera in package.get('cameras', [])]
                == profile['cameraOrder'], 'Package camera/site order differs')
    tracker = yaml.safe_load(files['tracker-mv3dt.experimental.yml'])
    original = deepcopy(tracker)
    assoc = tracker['MultiViewAssociator']
    require(assoc.get('multiViewAssociatorType') == 1
            and assoc.get('enableSeeThrough') == 0, 'Expected guarded native MV3DT baseline')
    changes = []
    for key in ('enableLatePeerReAssoc', 'enableIDCorrection'):
        require(type(assoc.get(key)) is int and assoc[key] == 1,
                'Expected explicit enabled baseline: ' + key)
        assoc[key] = 0
        changes.append({'path': 'MultiViewAssociator.' + key, 'before': 1, 'after': 0})
    # Only references to the cloned pinned files move. Topic bytes and all
    # model/camera/numerical settings remain unchanged.
    references = []
    def rebased(value):
        require(isinstance(value, str) and value.startswith('/state/' + old),
                'Tracker file reference escaped its pinned snapshot')
        name = value[len('/state/' + old):]
        require(name in FILES and '/' not in name, 'Unpinned tracker file reference')
        references.append({'before': value, 'after': '/state/' + new + name})
        return '/state/' + new + name
    camera_paths = tracker['ObjectModelProjection']['cameraModelFilepath']
    require(camera_paths == ['/state/' + old + f'camera-{i}.yml' for i in range(2)],
            'Tracker camera file order differs')
    tracker['ObjectModelProjection']['cameraModelFilepath'] = [rebased(p) for p in camera_paths]
    comm = tracker['Communicator']
    require(comm.get('communicatorType') == 2, 'Expected MQTT communicator')
    for key, name in (('pubSubInfoConfigPath', 'pub-sub.yml'),
                      ('mqttProtoAdaptorConfigPath', 'mqtt.ini')):
        require(comm.get(key) == '/state/' + old + name, 'Unexpected communicator file reference')
        comm[key] = rebased(comm[key])
    restored = deepcopy(tracker)
    restored['MultiViewAssociator'].update(enableLatePeerReAssoc=1, enableIDCorrection=1)
    restored['ObjectModelProjection']['cameraModelFilepath'] = camera_paths
    restored['Communicator'] = original['Communicator']
    calibration.same(restored, original, 'Only the two declared tracker flags may change')
    files['tracker-mv3dt.experimental.yml'] = yaml.safe_dump(tracker, sort_keys=False).encode()
    policy = {'schemaVersion': 'city.mv3dt-identity-policy.v1', 'name': VARIANT,
              'candidateOnly': True, 'runtimeQualified': False,
              'notAStableSdkLocalHandle': True, 'parentProfileSha256': calibration.sha(rollback),
              'changes': changes, 'rebasedFileReferences': references,
              'initialPeerAssociationPreserved': True,
              'lateMissedMatchesWillRemainSeparate': True,
              'incorrectInitialMatchesWillNotBeCorrected': True,
              'existingMapGuardsUnchanged': True}
    manifest = json.loads(files['manifest.json'])
    manifest.update(identityPolicyVariant=policy, runtimeQualified=False,
                    transportClockQualified=False, diagnosticOnly=True, enabled=False)
    files['manifest.json'] = calibration.encoded(manifest)
    candidate = deepcopy(profile)
    candidate.update(trackerConfig=new + 'tracker-mv3dt.experimental.yml',
                     identityPolicyVariant=policy, productionQualified=False)
    candidate['fileHashes'] = {new + name: calibration.sha(data)
                              for name, data in sorted(files.items())}
    require(active.read_bytes() == rollback and demo.load(root, 'spark') == profile
            and export_path.read_bytes() == export_bytes, 'Source profile changed during preparation')
    return {'profile': candidate, 'rollback': rollback, 'files': files,
            'export': export_bytes, 'prefix': new,
            'receipt': {'schemaVersion': 'city.mv3dt-stable-ids-preparation.v1',
                        'preparedOnly': True, 'runtimeChanged': False, 'variant': VARIANT,
                        'sourceActiveProfile': str(active),
                        'sourceActiveSha256': calibration.sha(rollback),
                        'sourceFileHashes': profile['fileHashes'],
                        'staticExportSha256': calibration.sha(export_bytes),
                        'candidateProfileSha256': calibration.sha(calibration.encoded(candidate)),
                        'candidateFileHashes': candidate['fileHashes'],
                        'cameraCalibrations': candidate['cameraCalibrations'],
                        'imageId': candidate['imageId'], 'policy': policy}}


def write_review(output: Path, result: dict) -> None:
    calibration.require(not output.exists(), 'Output must be a new review directory')
    output.mkdir(parents=True)
    clone = output / result['prefix']
    clone.mkdir(parents=True)
    for name, data in result['files'].items():
        (clone / name).write_bytes(data)
    (clone / 'current-static-export.json').write_bytes(result['export'])
    (output / 'active.json').write_bytes(calibration.encoded(result['profile']))
    (output / 'rollback-active.json').write_bytes(result['rollback'])
    # Exercise the same runtime loader against this review bundle, never the
    # active state. This is entirely CPU/text validation.
    import tempfile
    import shutil
    with tempfile.TemporaryDirectory(prefix='city-stable-ids-') as temporary:
        root = Path(temporary)
        state = root / '.spark/city/state'
        shutil.copytree(output / 'native', state / 'native')
        shutil.copyfile(output / 'active.json', state / PREFIX / 'active.json')
        if result.get('modelRoot') is not None:
            (root/'.spark/city/models').symlink_to(result['modelRoot'], target_is_directory=True)
        calibration.require(demo.load(root, 'spark') == result['profile'],
                            'Candidate failed the actual runtime profile loader')
    receipt = deepcopy(result['receipt'])
    receipt.update(runtimeLoaderValidationPassed=True,
                   generatorSha256=calibration.sha(Path(__file__).read_bytes()))
    (output / 'receipt.json').write_bytes(calibration.encoded(receipt))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root.resolve(), args.snapshot)
    write_review(args.output.resolve(), result)
    print(json.dumps({'output': str(args.output.resolve()), **result['receipt']}, indent=2))


if __name__ == '__main__':
    main()
