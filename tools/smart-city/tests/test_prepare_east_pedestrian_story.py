# SPDX-License-Identifier: Apache-2.0
"""Operator preservation and actual crossing state-machine regressions; CPU only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

TOOLS = Path(__file__).parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parents[1] / 'services/analytics/behavior-analytics'))
import isaac_site
import isaac_mobility
import prepare_east_pedestrian_story as candidate
from apps.city.geometry import point_in_polygon, project
from apps.city.mobility import configuration_issues
from apps.city.mobility_spatial import MobilitySpatial
from apps.city.models import MobilityConfig, Rule, Site

PACKAGE = json.loads((Path(__file__).parent / 'fixtures/isaac-movement-camera-export.json').read_text())


def fixture():
    package = deepcopy(PACKAGE)
    site, saved = isaac_site.build(package, {'cam_SW': {'id': 'sw', 'name': 'isaac-intersection-southwest'},
                                           'cam_NE': {'id': 'ne', 'name': 'isaac-intersection-northeast'}})
    rules, config = isaac_mobility.build(package, site, saved)
    site['revision'] = 142
    config.update(revision=4, operatorExtra='retain')
    config['curbs'][0]['dwellThresholdMs'] = 8000
    for r in rules:
        r['operatorNote'] = 'retain ' + r['id']
    snapshot = {'site': site, 'rules': {'rules': rules, 'revision': 405}, 'mobility': {'config': config}}
    survey = {'crosswalks': deepcopy(package['crosswalks'])}
    # Stub only the static-audit boundary. The CLI review uses the real ray receipt.
    audit = {'schemaVersion': 'city.pedestrian-pocket-static-audit.v1',
             'cameras': {'cam_SW': {'eye': package['cameras']['cam_SW']['cameraPositionWorldM']}},
             'cameraRays': [{'name': name, 'camera': 'cam_SW', 'samples': [{'insideImage': True, 'currentCityHits': []} for _ in range(3)]}
                            for name in ['east-south-wait', 'east-south-edge', 'east-midpoint', 'east-north-edge', 'east-north-wait']]}
    return snapshot, package, survey, audit


def test_candidate_preserves_every_existing_rule_and_nonpedestrian_operator_configuration():
    args = fixture(); before = deepcopy(args)
    result = candidate.prepare(*args)
    assert args == before
    for old in args[0]['rules']['rules']:
        assert next(r for r in result['rulesPut']['rules'] if r['id'] == old['id']) == old
    config = result['mobilityPut']
    for key, value in args[0]['mobility']['config'].items():
        if key != 'crossings': assert config[key] == value
    assert len(config['crossings']) == 2
    assert [c['id'] for c in config['crossings']] == list(candidate.EAST)
    assert result['rulesPut']['expectedRevision'] == 405
    assert config['expectedRevision'] == 4
    assert result['site'] == args[0]['site']
    assert result['summary']['runtimeChanged'] is False
    for new in result['rulesPut']['rules'][-3:]:
        assert new['sourceId'] == 'sw'
        assert new['conditions']['maximumObservationGapMs'] == 1000
        assert new['classes'] == ['person']


def test_actual_models_validate_references_and_every_roi_vertex_has_valid_owner_projection():
    result = candidate.prepare(*fixture()); site = Site.model_validate(result['site'])
    rules = [Rule.model_validate(r) for r in result['rulesPut']['rules']]
    config = MobilityConfig.model_validate(result['mobilityPut'])
    assert configuration_issues(config, site, rules) == []
    camera = site.sources[0]
    for rule in rules[-3:]:
        inverse = isaac_site.invert3(camera.classImageToGroundHomographies['person'])
        for world in rule.geometry.points:
            pixel = isaac_site.project(inverse, world)
            recovered, status = project(pixel, camera.classImageToGroundHomographies['person'], camera.validGroundPolygon, site.map.bounds)
            assert status == 'valid'
            assert recovered == pytest.approx(world)
    crossing = next(r for r in rules if r.id == candidate.CROSS)
    assert crossing.geometry.points == next(c for c in PACKAGE['crosswalks'] if c['id'] == 'XW_E')['polygon']
    assert not point_in_polygon([-11.2, 70], crossing.geometry.points)
    assert point_in_polygon([-11.2, 79.2], crossing.geometry.points)
    assert not point_in_polygon([-11.2, 88.4], crossing.geometry.points)


@pytest.mark.parametrize('direction', ['south-north', 'north-south'])
def test_real_state_machine_counts_only_correct_direction_with_same_local_handle(direction):
    result = candidate.prepare(*fixture()); site = Site.model_validate(result['site']); source = site.sources[0]
    rules = [Rule.model_validate(r) for r in result['rulesPut']['rules']]
    config = result['mobilityPut']; spatial = MobilitySpatial()
    ys = [68.9, 70, 71.5, 73, 79.2, 85, 86.6, 88.4]
    if direction == 'north-south': ys = list(reversed(ys))
    for i, y in enumerate(ys):
        ns=(i+1)*400_000_000
        spatial.update('sw', 'session', ns, [{'id':'actual-local-1','sourceId':'sw','sessionId':'session',
            'class':'person','positionM':[-11.2,y],'anchorPx':[500,200], 'observedThisFrame':True,'stale':False,
            'sourceTimeNsInt':ns}], rules, source, config, emit_snapshot=False)
    counts={c['id']:c for c in spatial.snapshot()['crossings']}
    assert counts['east-crossing-'+direction]['completedCount'] == 1
    opposite='north-south' if direction=='south-north' else 'south-north'
    assert counts['east-crossing-'+opposite]['completedCount'] == 0


def test_different_id_across_far_boundary_does_not_create_completion():
    result = candidate.prepare(*fixture()); source=Site.model_validate(result['site']).sources[0]
    rules=[Rule.model_validate(r) for r in result['rulesPut']['rules']]; spatial=MobilitySpatial()
    for i,y in enumerate([70,73,80,86.2,87]):
        ns=(i+1)*400_000_000
        spatial.update('sw','session',ns,[{'id':'first' if i<4 else 'replacement','sourceId':'sw','sessionId':'session',
            'class':'person','positionM':[-11.2,y],'anchorPx':[500,200],'observedThisFrame':True,'stale':False,
            'sourceTimeNsInt':ns}],rules,source,result['mobilityPut'],emit_snapshot=False)
    assert all(c['completedCount']==0 for c in spatial.snapshot()['crossings'])


@pytest.mark.parametrize('fault', ['camera','calibration','signal','crossing','occluded','missing-ray','custom-selection','conflicting-rule'])
def test_changed_evidence_or_operator_conflicts_fail_closed(fault):
    snapshot, package, survey, audit=fixture()
    if fault=='camera': package['cameras']['cam_SW']['width']+=1
    elif fault=='calibration': package['calibrationRevision']='changed'
    elif fault=='signal': next(c for c in survey['crosswalks'] if c['id']=='XW_E')['ped_signal']='ped_cross_NS'
    elif fault=='crossing': next(c for c in survey['crosswalks'] if c['id']=='XW_E')['polygon'][0][0]-=1
    elif fault=='occluded': audit['cameraRays'][0]['samples'][0]['currentCityHits']=[{'path':'building'}]
    elif fault=='missing-ray': audit['cameraRays'].pop()
    elif fault=='custom-selection': snapshot['mobility']['config']['crossings'][0]['id']='operator-custom'
    else: snapshot['rules']['rules'].append({**deepcopy(snapshot['rules']['rules'][0]),'id':candidate.WAIT_S})
    with pytest.raises(ValueError): candidate.prepare(snapshot,package,survey,audit)


def test_reprepare_selected_east_is_noop_and_cli_writes_guarded_restorable_bundle(tmp_path):
    snapshot, package, survey, audit=fixture(); first=candidate.prepare(snapshot,package,survey,audit)
    snapshot['rules']={'revision':406,'rules':first['rulesPut']['rules']}
    snapshot['mobility']['config']={k:v for k,v in first['mobilityPut'].items() if k!='expectedRevision'}
    snapshot['mobility']['config']['revision']=5
    second=candidate.prepare(snapshot,package,survey,audit)
    assert not second['summary']['rulesChangeRequired'] and not second['summary']['mobilityChangeRequired']
    paths=[]
    for label,value in zip(['snapshot','camera-export','survey','static-visibility-audit'],[snapshot,package,survey,audit]):
        path=tmp_path/(label+'.json');path.write_text(json.dumps(value));paths.extend(['--'+label,str(path)])
    target=tmp_path/'review'
    result=subprocess.run([sys.executable,str(TOOLS/'prepare_east_pedestrian_story.py'),*paths,'--output',str(target)],
                          capture_output=True,text=True,check=True,timeout=10)
    assert json.loads(result.stdout)['runtimeChanged'] is False
    assert json.loads((target/'before.json').read_text())==snapshot
    assert not (target/'south-selection-archive.json').exists()  # This reprepare started with East selected.
    assert json.loads((target/'previous-crossing-selection.json').read_text()) == snapshot['mobility']['config']['crossings']
    assert json.loads((target/'rollback-rules-template.json').read_text())['expectedRevision']==candidate.CURRENT_REVISION_PLACEHOLDER
    manifest=json.loads((target/'manifest.json').read_text())
    for name,digest in manifest['outputSha256'].items():assert hashlib.sha256((target/name).read_bytes()).hexdigest()==digest
