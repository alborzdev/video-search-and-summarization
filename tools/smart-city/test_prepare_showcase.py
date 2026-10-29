"""Static calibration/migration contracts, no service or actor dependencies."""
import pytest
from prepare_showcase import build


def fixture():
    h=[[.1,0,-50],[0,.1,60],[0,0,1]]
    package={'cameraOrder':['cam_SW','cam_NE'],'calibrationRevision':'reviewed',
        'cameras':{'cam_NE':{'width':1280,'height':480,'imageToGroundHomography':h},'cam_SW':{'width':1280,'height':480,'imageToGroundHomography':h,'classImageToGroundHomographies':{'person':h}}},
        'crosswalks':[{'id':'XW_E','polygon':[[-13.2,72],[-9.2,72],[-9.2,86.4],[-13.2,86.4]]}]}
    site={'id':'isaac-intersection-a','sources':[{'id':'sw','name':'isaac-intersection-southwest','calibrationRevision':'reviewed'},
        {'id':'ne','name':'isaac-intersection-northeast','calibrationRevision':'reviewed'}]}
    return package,site


def test_retires_only_named_legacy_rules_and_preserves_custom_rules_and_references():
    package,site=fixture()
    custom={'id':'operator-curb','enabled':False,'revision':9,'name':'Custom curb'}
    queue={'id':'custom','zoneRuleId':'operator-curb','name':'Keep my queue'}
    rules,config=build(package,site,{'rules':[custom,{'id':'cam_sw-northbound-line'}]},
        {'queues':[queue,{'id':'legacy','zoneRuleId':'mobility-isaac-northbound-queue'}]})
    assert rules[0]==custom and config['queues']==[queue]
    assert len(rules)==5
    crossing=next(r for r in rules if r['id']=='expo-crossing-occupancy')
    assert crossing['classes']==['person']
    assert crossing['sourceId']=='ne'
    assert all(0<=v<=1 for point in crossing['geometry']['points'] for v in point)


def test_changed_calibration_or_off_camera_crossing_refuses_before_any_mutation():
    package,site=fixture();site['sources'][1]['calibrationRevision']='different'
    with pytest.raises(ValueError,match='calibration has changed'):build(package,site,{'rules':[]},{})
    package,site=fixture();package['cameras']['cam_SW']['imageToGroundHomography']=[[.0001,0,0],[0,.0001,0],[0,0,1]]
    with pytest.raises(ValueError,match='does not fit'):build(package,site,{'rules':[]},{})


def test_crossing_roi_uses_painted_road_plane_for_camera_map_round_trip():
    from isaac_site import project
    package,site=fixture()
    camera=package['cameras']['cam_NE']
    camera['classImageToGroundHomographies']={'person':[[.1,0,-48],[0,.1,63],[0,0,1]]}
    rules,_=build(package,site,{'rules':[]},{})
    crossing=next(r for r in rules if r['id']=='expo-crossing-occupancy')
    actual=[project(camera['imageToGroundHomography'],[u*1280,v*480]) for u,v in crossing['geometry']['points']]
    expected=[[-14.,83.],[-10.7,82.85],[-10.7,72.7],[-14.,72.9]]
    for a,b in zip(actual,expected): assert a==pytest.approx(b)
    queue=next(r for r in rules if r['id']=='expo-approach-queue')
    ground=[project(package['cameras']['cam_SW']['imageToGroundHomography'],[u*1280,v*480]) for u,v in queue['geometry']['points']]
    assert min(p[1] for p in ground)>=93 # Beyond the north crossing/stop line.

def test_emergency_area_measures_cross_traffic_without_the_waiting_ambulance():
    from isaac_site import project
    package,site=fixture()
    rules,_=build(package,site,{'rules':[]},{})
    emergency=next(r for r in rules if r['id']=='expo-emergency-blockage')
    ground=[project(package['cameras']['cam_SW']['imageToGroundHomography'],[u*1280,v*480]) for u,v in emergency['geometry']['points']]
    left,right=min(p[0] for p in ground),max(p[0] for p in ground)
    assert left < -25.3 < -21.8 < right # Both opposing cross-traffic lanes.
    assert right < -14.5-3.5 # Exclude the ambulance's conservative body envelope.
