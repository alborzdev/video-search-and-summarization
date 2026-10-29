# SPDX-License-Identifier: Apache-2.0
"""Preset ownership and fail-closed CLI controls; no API or simulator calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).parents[1]
sys.path.insert(0, str(TOOLS))
import isaac_mobility as mobility
import isaac_site

PACKAGE = json.loads((Path(__file__).parent / 'fixtures/isaac-movement-camera-export.json').read_text())
EAST_IDS = ('mobility-isaac-east-waiting-south', 'mobility-isaac-east-crossing-measurement',
            'mobility-isaac-east-waiting-north')


def fixture():
    site, saved = isaac_site.build(deepcopy(PACKAGE), {
        'cam_SW': {'id': 'sw', 'name': 'isaac-intersection-southwest'},
        'cam_NE': {'id': 'ne', 'name': 'isaac-intersection-northeast'}})
    saved['revision'] = 415
    for i, identifier in enumerate(EAST_IDS):
        saved['rules'].append({'id': identifier, 'name': 'Operator East ' + str(i), 'kind': 'occupancy-threshold',
            'sourceId': 'sw', 'classes': ['person'], 'geometry': {'space': 'site-metres',
            'points': [[-12.2, 69.2], [-10.2, 69.2], [-10.2, 72], [-12.2, 72]]},
            'conditions': {'maximumObservationGapMs': 777, 'countThreshold': 913}, 'enabled': True,
            'revision': 415, 'calibrationRevision': PACKAGE['calibrationRevision'], 'customOperatorNote': 'retain'})
    config = {'revision': 6, 'movements': [], 'queues': [], 'curbs': [], 'crossings': [
        {'id': 'east-crossing-south-north', 'name': 'East to north', 'waitingRuleId': EAST_IDS[0], 'crossingRuleId': EAST_IDS[1]},
        {'id': 'east-crossing-north-south', 'name': 'East to south', 'waitingRuleId': EAST_IDS[2], 'crossingRuleId': EAST_IDS[1]}]}
    return site, saved, config


def test_preserves_reviewed_east_and_arbitrary_prefixed_operator_rules_exactly():
    site, saved, _ = fixture()
    custom = {**deepcopy(saved['rules'][-1]), 'id': 'mobility-isaac-operator-custom', 'enabled': False,
              'conditions': {'minimumDurationMs': 123456}, 'name': 'Keep disabled custom rule'}
    saved['rules'].append(custom); original = deepcopy(saved)
    rules, _ = mobility.build(PACKAGE, site, saved)
    by_id = {rule['id']: rule for rule in rules}
    for rule in original['rules']:
        assert by_id[rule['id']] == rule
    assert saved == original
    assert len(by_id) == len(rules)


def test_replaces_only_generated_ids_once_and_advances_preset_revision():
    site, saved, _ = fixture()
    first, _ = mobility.build(PACKAGE, site, saved)
    north = next(r for r in first if r['id'] == 'mobility-isaac-north-exit')
    north['revision'] = 8
    repeated, _ = mobility.build(PACKAGE, site, {'rules': first})
    assert len(repeated) == len(first)
    assert next(r for r in repeated if r['id'] == north['id'])['revision'] == 9
    assert {r['id'] for r in repeated} == {r['id'] for r in first}


@pytest.mark.parametrize(('kind', 'fields'), [
    ('movements', {'entryRuleId': 'present', 'exitRuleId': 'missing'}),
    ('crossings', {'waitingRuleId': 'present', 'crossingRuleId': 'missing'}),
    ('queues', {'zoneRuleId': 'missing'}), ('curbs', {'zoneRuleId': 'missing'})])
def test_missing_saved_references_fail_before_replacement(kind, fields):
    config = {kind: [{'id': 'keep-operator-measurement', **fields}]}
    before = deepcopy(config)
    with pytest.raises(ValueError, match=kind + '/keep-operator-measurement: missing'):
        mobility.validate_saved_mobility_references(config, [{'id': 'present'}])
    assert config == before


def run_cli(monkeypatch, tmp_path, *, missing=False):
    site, saved, config = fixture()
    if missing: config['crossings'][0]['crossingRuleId'] = 'missing-operator-rule'
    camera = tmp_path / 'camera.json'; camera.write_text(json.dumps(PACKAGE))
    calls = []
    def request(path, payload=None):
        calls.append((path, deepcopy(payload)))
        if payload is not None: return {'status': 'saved'}
        return deepcopy({'site': site, 'rules': saved, 'mobility': {'config': config}}[path])
    monkeypatch.setattr(mobility, 'request', request)
    monkeypatch.setattr(sys, 'argv', ['isaac_mobility.py', '--camera-package', str(camera), '--apply'])
    return calls, config, saved


def test_actual_apply_control_retains_all_east_rules_and_existing_selection(monkeypatch, tmp_path):
    calls, config, saved = run_cli(monkeypatch, tmp_path)
    mobility.main()
    puts = [(path, payload) for path, payload in calls if payload is not None]
    assert len(puts) == 1 and puts[0][0] == 'rules'
    body = puts[0][1]; by_id = {r['id']: r for r in body['rules']}
    assert body['expectedRevision'] == 415
    for rule in saved['rules']:
        assert by_id[rule['id']] == rule
    assert {r['id'] for r in body['rules']} >= set(EAST_IDS)
    mobility.validate_saved_mobility_references(config, body['rules'])
    assert not any(path == 'mobility/config' for path, _ in calls)


def test_actual_apply_control_refuses_dangling_reference_without_any_put(monkeypatch, tmp_path):
    calls, _, _ = run_cli(monkeypatch, tmp_path, missing=True)
    with pytest.raises(ValueError, match='Refusing preset apply.*missing-operator-rule'):
        mobility.main()
    assert calls and all(payload is None for _, payload in calls)
