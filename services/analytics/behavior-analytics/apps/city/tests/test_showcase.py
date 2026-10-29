"""Camera-observation tests. These do not qualify recognition accuracy."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from apps.city.engine import CityEngine
from apps.city.models import Observation, RuleSet, Site
from apps.city.store import CityStore

BASE=1_790_000_000_000_000_000

def setup(tmp_path,kind='occupancy-threshold'):
    clock=[100.]
    engine=CityEngine(store=CityStore(str(tmp_path/'city.sqlite')),clock=lambda:clock[0])
    engine.put_site(Site.model_validate({'id':'test','mode':'fixture-replay','sources':[{'id':'cam','width':100,'height':100,
        'imageToGroundHomography':[[.1,0,0],[0,.1,0],[0,0,1]],'calibrationRevision':'fixture'}]}))
    identifier='expo-crossing-occupancy' if kind=='occupancy-threshold' else 'expo-junction-blockage'
    engine.put_rules(RuleSet.model_validate({'rules':[{'id':identifier,'name':'Test area','sourceId':'cam','kind':kind,'classes':['person' if kind=='occupancy-threshold' else 'car'],
        'geometry':{'space':'image-normalized','points':[[.1,.1],[.9,.1],[.9,.9],[.1,.9]]},
        'conditions':{'minimumDurationMs':100 if kind=='occupancy-threshold' else 1000,'clearAfterMs':100,'maximumObservationGapMs':750}}]}))
    engine.reset_analytics_scope(kind='scenario',run_id='run-a',scenario_id='crossing-occupancy' if kind=='occupancy-threshold' else 'queue-blockage')
    return engine,clock

def frame(engine,clock,t,ids=('one',),session='s',cls='person'):
    clock[0]=100+t
    engine.ingest(Observation.model_validate({'siteId':'test','sourceId':'cam','sourceSessionId':session,'sequence':str(round(t*100)+1),
        'sourceTimeNs':str(BASE+round(t*1e9)),'timestampBasis':'fixture-epoch-plus-pts','mediaTimeSeconds':t,
        'image':{'width':100,'height':100},'objects':[{'localTrackId':id,'class':cls,'confidence':.9,'bboxPx':[40,30,10,20]} for id in ids]}))
    return engine.showcase.snapshot(engine)[0]

def test_group_occupancy_is_union_time_and_events_are_durable(tmp_path):
    e,c=setup(tmp_path)
    frame(e,c,0,('one','two','three','four'))
    r=frame(e,c,.5,('one','two','three','four'))
    assert r['count']==4 and r['peakCount']==4
    assert r['occupiedSeconds']==pytest.approx(.5) # not 4 person-seconds
    assert len(r['savedEventIds'])==1
    assert r['savedEventIds'][0] in {x['id'] for x in e.store.events(site_id='test')}
    r=frame(e,c,1,('one','two','three','four'))
    assert r['continuousSeconds']==1
    e.reset_analytics_scope(kind='normal')
    assert not e.showcase.rows
    archive=e.store.get('analytics-scopes:test')[-1]
    assert archive['showcase'][0]['occupiedSeconds']==1
    assert archive['scenarioId']=='crossing-occupancy'

def test_no_clock_extrapolation_and_no_time_across_gap_or_session(tmp_path):
    e,c=setup(tmp_path)
    frame(e,c,0);r=frame(e,c,.5)
    c[0]=120
    assert e.showcase.snapshot(e)[0]['count'] is None
    assert e.showcase.snapshot(e)[0]['occupiedSeconds']==.5
    r=frame(e,c,4)
    assert r['occupiedSeconds']==.5 and r['continuousSeconds']==0 and r['hasGaps']
    r=frame(e,c,4.5,session='new')
    assert r['occupiedSeconds']==0 and r['hasGaps']

def test_passing_vehicle_does_not_become_stopped_count(tmp_path):
    e,c=setup(tmp_path,'stopped-in-zone')
    r=frame(e,c,0,cls='car'); assert r['count']==0
    for t in (.25,.5,.75,1,1.25,1.5,1.75):r=frame(e,c,t,cls='car')
    assert r['count']==1 and r['savedEventIds']

def test_preparation_and_other_scenario_cannot_supply_readouts(tmp_path):
    e,c=setup(tmp_path)
    e.reset_analytics_scope(kind='preparing',run_id='run-b',scenario_id='crossing-occupancy',suppressed=True)
    # Suppressed ingestion has no measurements.
    clock=[100.]
    e.reset_analytics_scope(kind='scenario',run_id='run-b',scenario_id='emergency-access')
    e.ingest(Observation.model_validate({'siteId':'test','sourceId':'cam','sourceSessionId':'s','sequence':'1','sourceTimeNs':str(BASE),
        'timestampBasis':'fixture-epoch-plus-pts','mediaTimeSeconds':0,'image':{'width':100,'height':100},'objects':[]}))
    assert not e.showcase.rows
