# SPDX-License-Identifier: Apache-2.0
"""Pure operator-preservation and real static route regressions; no services."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

TOOLS = Path(__file__).parents[1]
sys.path.insert(0, str(TOOLS))
import isaac_movement_gates as migration
import isaac_site as site_generator
import isaac_mobility as mobility_generator

PACKAGE = json.loads((Path(__file__).parent / 'fixtures/isaac-movement-camera-export.json').read_text())


def fixture():
    registration = {'cam_SW': {'id': 'sw', 'name': 'isaac-intersection-southwest'},
                    'cam_NE': {'id': 'ne', 'name': 'isaac-intersection-northeast'}}
    site, rules = site_generator.build(deepcopy(PACKAGE), registration)
    generated, config = mobility_generator.build(PACKAGE, site, rules)
    rules = {'revision': 17, 'rules': [r for r in generated if r['id'] != migration.RIGHT_EXIT]}
    by_id = {r['id']: r for r in rules['rules']}
    by_id[migration.ENTRY]['geometry'] = site_generator.northbound_entry_geometry(
        PACKAGE, PACKAGE['cameras']['cam_SW'], line_y=69.6, include_anchor_margin=False)
    by_id[migration.ENTRY].update(name='Operator entry name', operatorNote='keep')
    by_id[migration.ENTRY]['conditions']['maximumObservationGapMs'] = 777
    by_id[migration.OLD_EXIT]['conditions'].update(countThreshold=3, lineHysteresis=.12)
    by_id['cam_ne-blocked-crossing']['conditions']['minimumDurationMs'] = 9123
    by_id['cam_ne-blocked-crossing']['enabled'] = False
    config.update(revision=4, customOperatorNote='retain')
    config['curbs'][0].update(dwellThresholdMs=8000, role='general')
    right = next(m for m in config['movements'] if m['id'] == migration.RIGHT_MOVEMENT)
    right.update(exitRuleId=migration.OLD_EXIT, name='My right-turn count', classes=['car', 'motorcycle'])
    site['revision'] = 130
    return {'site': site, 'rules': rules, 'mobility': {'config': config}}


def test_prepare_changes_only_intended_geometry_and_reference_preserving_operator_values():
    snapshot = fixture(); original = deepcopy(snapshot); package = deepcopy(PACKAGE)
    result = migration.prepare(snapshot, package)
    assert snapshot == original and package == PACKAGE
    assert result['site'] == original['site']
    assert result['rulesPut']['expectedRevision'] == 17
    assert result['mobilityPut']['expectedRevision'] == 4
    after = {r['id']: r for r in result['rulesPut']['rules']}
    for before in original['rules']['rules']:
        expected = deepcopy(before)
        if before['id'] == migration.ENTRY:
            expected['geometry'] = site_generator.northbound_entry_geometry(PACKAGE, PACKAGE['cameras']['cam_SW'])
        assert after[before['id']] == expected
    old_east = next(r for r in original['rules']['rules'] if r['id'] == migration.OLD_EXIT)
    assert after[migration.RIGHT_EXIT]['conditions'] == old_east['conditions']
    assert after[migration.RIGHT_EXIT]['classes'] == old_east['classes']
    expected_config = deepcopy(original['mobility']['config'])
    next(m for m in expected_config['movements'] if m['id'] == migration.RIGHT_MOVEMENT)['exitRuleId'] = migration.RIGHT_EXIT
    assert result['mobilityPut'] == {**expected_config, 'expectedRevision': 4}
    assert result['summary']['cameraAndSiteUpdateRequired'] is False
    assert result['summary']['runtimeChanged'] is False
    assert result['summary']['changesRequired'] is True


def test_already_migrated_snapshot_is_noop_not_another_history_reset():
    snapshot = fixture(); first = migration.prepare(snapshot, PACKAGE)
    snapshot['rules'] = {'rules': first['rulesPut']['rules'], 'revision': 18}
    snapshot['mobility']['config'] = {k: v for k, v in first['mobilityPut'].items() if k != 'expectedRevision'}
    snapshot['mobility']['config']['revision'] = 5
    result = migration.prepare(snapshot, PACKAGE)
    assert result['summary']['changesRequired'] is False
    assert len(result['rulesPut']['rules']) == len(snapshot['rules']['rules'])
    assert result['rulesPut']['rules'] == snapshot['rules']['rules']


def test_known_narrow_early_entry_can_migrate_without_overwriting_custom_geometry():
    snapshot = fixture()
    next(r for r in snapshot['rules']['rules'] if r['id'] == migration.ENTRY)['geometry'] = \
        site_generator.northbound_entry_geometry(PACKAGE, PACKAGE['cameras']['cam_SW'], include_anchor_margin=False)
    result = migration.prepare(snapshot, PACKAGE)
    assert result['summary']['entryRule']['geometryChanged'] is True
    after = next(r for r in result['rulesPut']['rules'] if r['id'] == migration.ENTRY)
    before = next(r for r in snapshot['rules']['rules'] if r['id'] == migration.ENTRY)
    assert after['geometry']['points'][1] == before['geometry']['points'][1]
    assert after['geometry']['direction'] == before['geometry']['direction']
    assert after['conditions'] == before['conditions']
    altered = deepcopy(snapshot)
    next(r for r in altered['rules']['rules'] if r['id'] == migration.ENTRY)['geometry']['points'][0][0] -= .001
    with pytest.raises(ValueError, match='Operator changed entry geometry'):
        migration.prepare(altered, PACKAGE)


@pytest.mark.parametrize('change', ['calibration', 'camera', 'duplicate-source', 'roads', 'custom-entry', 'custom-reference', 'deleted-movement', 'disabled', 'conflicting-right'])
def test_prepare_rejects_camera_or_operator_conflicts(change):
    snapshot, package = fixture(), deepcopy(PACKAGE)
    by_id = {r['id']: r for r in snapshot['rules']['rules']}
    right = next(m for m in snapshot['mobility']['config']['movements'] if m['id'] == migration.RIGHT_MOVEMENT)
    if change == 'calibration': package['calibrationRevision'] = 'different'
    elif change == 'camera': package['cameras']['cam_SW']['imageToGroundHomography'][0][0] += .1
    elif change == 'duplicate-source': snapshot['site']['sources'][1]['id'] = snapshot['site']['sources'][0]['id']
    elif change == 'roads': package['map']['roads'][0]['width'] += .1
    elif change == 'custom-entry': by_id[migration.ENTRY]['geometry']['points'][0][0] += .02
    elif change == 'custom-reference': right['exitRuleId'] = 'my-custom-exit'
    elif change == 'deleted-movement': snapshot['mobility']['config']['movements'].remove(right)
    elif change == 'disabled': by_id[migration.ENTRY]['enabled'] = False
    elif change == 'conflicting-right': snapshot['rules']['rules'].append({**deepcopy(by_id[migration.OLD_EXIT]), 'id': migration.RIGHT_EXIT})
    with pytest.raises(ValueError): migration.prepare(snapshot, package)


def test_cli_saves_complete_baseline_and_revision_guarded_rollback_material(tmp_path):
    snapshot = fixture()
    source = tmp_path / 'before.json'; source.write_text(json.dumps(snapshot))
    package = Path(__file__).parent / 'fixtures/isaac-movement-camera-export.json'
    output = tmp_path / 'candidate'
    completed = subprocess.run([sys.executable, str(TOOLS / 'isaac_movement_gates.py'),
                               '--snapshot', str(source), '--camera-export', str(package),
                               '--output', str(output)], check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(completed.stdout)['runtimeChanged'] is False
    assert json.loads((output / 'before.json').read_text()) == snapshot
    assert json.loads((output / 'rollback-rules-template.json').read_text()) == {
        'rules': snapshot['rules']['rules'], 'expectedRevision': migration.CURRENT_REVISION_PLACEHOLDER}
    assert json.loads((output / 'rollback-mobility-template.json').read_text()) == {
        **{key: value for key, value in snapshot['mobility']['config'].items() if key != 'revision'},
        'expectedRevision': migration.CURRENT_REVISION_PLACEHOLDER}
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['rulesChangeRequired'] is True and manifest['mobilityChangeRequired'] is True
    import hashlib
    for name, digest in manifest['outputSha256'].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


def test_generators_keep_old_east_gate_and_select_dedicated_outer_right_gate():
    snapshot = fixture()
    rules, config = mobility_generator.build(PACKAGE, snapshot['site'], snapshot['rules'])
    by_id = {r['id']: r for r in rules}
    assert migration.OLD_EXIT in by_id and migration.RIGHT_EXIT in by_id
    for actual, expected in zip(by_id[migration.OLD_EXIT]['geometry']['points'],
                                [[-7.5, 75.83376851248642], [-7.5, 79.33376851248642]]):
        assert actual == pytest.approx(expected)
    assert next(m for m in config['movements'] if m['id'] == migration.RIGHT_MOVEMENT)['exitRuleId'] == migration.RIGHT_EXIT
    assert next(m for m in config['movements'] if m['id'] == 'northbound-through')['exitRuleId'] == 'mobility-isaac-north-exit'
    assert next(m for m in config['movements'] if m['id'] == 'northbound-left')['exitRuleId'] == 'mobility-isaac-west-exit'


def _intersections(lane, line):
    def cross(a, b): return a[0]*b[1] - a[1]*b[0]
    hits = []
    for j, (a, b) in enumerate(zip(zip(lane.xs, lane.ys), zip(lane.xs[1:], lane.ys[1:]))):
        v, w, u = ([b[k]-a[k] for k in (0, 1)], [line[1][k]-line[0][k] for k in (0, 1)], [line[0][k]-a[k] for k in (0, 1)])
        denominator = cross(v, w)
        if abs(denominator) < 1e-12: continue
        t, f = cross(u, w)/denominator, cross(u, v)/denominator
        if 0 <= t <= 1 and 0 <= f <= 1:
            hits.append((.5*(j+t), [a[k]+t*v[k] for k in (0, 1)]))
    return hits


def test_real_traffic_routes_share_visible_entry_before_physical_turn_and_right_hits_outer_exit():
    city = Path('/home/sparkdev/isaac_city_sim')
    if not (city / 'scripts/traffic/vehicle_lib.py').is_file():
        pytest.skip('Optional Isaac City source checkout is absent; portable migration controls still run')
    spec = importlib.util.spec_from_file_location('gate_regression_vehicle', city / 'scripts/traffic/vehicle_lib.py')
    vl = importlib.util.module_from_spec(spec); sys.modules[spec.name] = vl; spec.loader.exec_module(vl)
    survey = vl.load_survey(str(city / 'config/survey_intersection_A.json'))
    survey['turns']['enabled'] = True
    sim = vl.TrafficSim(survey, seed=42)
    geometry = site_generator.northbound_entry_geometry(PACKAGE, PACKAGE['cameras']['cam_SW'])
    camera = PACKAGE['cameras']['cam_SW']
    entry = [site_generator.project(camera['imageToGroundHomography'], [p[0]*camera['width'], p[1]*camera['height']]) for p in geometry['points']]
    observed = []
    for route in ('NB_1', 'NB_1:L', 'NB_1:R'):
        hits = _intersections(sim.lanes[route], entry)
        assert len(hits) == 1
        assert hits[0][1] == pytest.approx([-21.87, 66.0])
        # branch_s is an earlier queue/heading accounting threshold. s_A is
        # the physical fillet's first point, which the common gate precedes.
        if ':' in route: assert hits[0][0] < sim.lanes[route].turn_meta['s_A']
        observed.append(hits[0][0])
    assert max(observed) - min(observed) < 1e-9
    right_exit = mobility_generator.right_exit_points(PACKAGE)
    right_hits = _intersections(sim.lanes['NB_1:R'], right_exit)
    assert len(right_hits) == 1
    assert right_hits[0][1] == pytest.approx([-7.5, 74.0771222846323], abs=1e-8)
    assert _intersections(sim.lanes['NB_1:R'], [[-7.5, 75.83376851248642], [-7.5, 79.33376851248642]]) == []
    inverse = site_generator.invert3(camera['imageToGroundHomography'])
    for point in (*entry, *right_exit):
        u, v = site_generator.project(inverse, point)
        assert 0 <= u <= 960 and 0 <= v <= 540


def test_default_anchor_margin_is_west_only_and_keeps_adjacent_lane_outside():
    camera = PACKAGE['cameras']['cam_SW']
    geometry = site_generator.northbound_entry_geometry(PACKAGE, camera)
    narrow = site_generator.northbound_entry_geometry(PACKAGE, camera, include_anchor_margin=False)
    world = [site_generator.project(camera['imageToGroundHomography'], [p[0] * camera['width'], p[1] * camera['height']])
             for p in geometry['points']]
    assert world[0] == pytest.approx([-24.37, 66])
    assert world[1] == pytest.approx([-20.12, 66])
    assert geometry['points'][1] == narrow['points'][1]
    assert geometry['direction'] == narrow['direction']
    # The nominal adjacent southbound centre remains outside the finite line.
    assert -25.37 < world[0][0]


@pytest.mark.parametrize('example', json.loads((Path(__file__).parent / 'fixtures/isaac-nb-entry-observed-anchors.json').read_text())['cases'],
                         ids=lambda value: value['name'])
def test_actual_retained_box_anchors_use_the_real_finite_directed_gate(example):
    sys.path.insert(0, str(TOOLS.parents[1] / 'services/analytics/behavior-analytics'))
    from apps.city.models import Rule
    from apps.city.mobility import _gate
    camera = PACKAGE['cameras']['cam_SW']
    def normalized(anchor):
        return [anchor[0] / camera['width'], anchor[1] / camera['height']]
    before, after = (normalized(example[key]['anchorPx']) for key in ('before', 'after'))
    rule = Rule.model_validate({'id': 'entry', 'name': 'Northbound', 'kind': 'line-crossing', 'sourceId': 'sw',
        'geometry': site_generator.northbound_entry_geometry(PACKAGE, camera),
        'conditions': {'maximumObservationGapMs': 1000}})
    assert 0 < int(example['after']['sourceTimeNs']) - int(example['before']['sourceTimeNs']) <= 1_000_000_000
    assert _gate(before, after, rule) is example['expectedCandidateHit']
    rule.geometry = type(rule.geometry).model_validate(site_generator.northbound_entry_geometry(PACKAGE, camera, include_anchor_margin=False))
    assert _gate(before, after, rule) is False
