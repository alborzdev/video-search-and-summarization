# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prototype_vehicle_map_association import VehicleMapAssociator, objects


def obj(identity='1', x=0, name='car'):
    return {'localTrackId':identity,'class':name,'observedThisFrame':True,
            'native3D':{'method':'nvidia-mv3dt-9.2','state':'observed','targetId':identity,
                        'calibrationRevision':'cal','worldPositionM':[x,0],'visibility':.8}}


def row(source,index,objects=None,session='session',timestamp=None):
    return {'sourceId':source,'sourceSessionId':source+session,'sourceFrameId':str(index),
            'sourceTimeNs':str(1_000_000_000+index*10_000_000 if timestamp is None else timestamp),
            'timestampBasis':'source-rtcp','fusionEpoch':'epoch','objects':[obj('1' if source=='a' else '99')] if objects is None else objects}


def tracker():return VehicleMapAssociator(['a','b'],'epoch',{'a':'cal','b':'cal'})


def confirmed(t):
    result=None
    for index in range(3):result=t.update(row('a',index),row('b',index))
    return result['associations'][0]


class GeometryPrototypeTests(unittest.TestCase):
    def test_three_fresh_pairs_confirm_different_native_ids(self):
        result=confirmed(tracker())
        self.assertEqual(result['targetIds'],['1','99'])
        self.assertFalse(result['nativeIdFusion'])
        self.assertEqual(result['method'],'calibrated-geometry-demo')

    def test_confirmed_lease_keeps_id_without_relabeling_native_ids(self):
        t=tracker();first=confirmed(t);second=t.update(row('a',3),row('b',3))['associations'][0]
        self.assertEqual(first['mapAssociationId'],second['mapAssociationId'])
        self.assertEqual(second['targetIds'],['1','99'])

    def test_current_distance_violation_splits_immediately(self):
        t=tracker();confirmed(t)
        self.assertEqual(t.update(row('a',3),row('b',3,[obj('99',1.001)]))['associations'],[])

    def test_current_clock_violation_splits_immediately(self):
        t=tracker();confirmed(t)
        self.assertEqual(t.update(row('a',3),row('b',3,timestamp=1_081_000_000))['associations'],[])

    def test_margin_required_in_first_direction(self):
        t=tracker();result=t.update(row('a',0),row('b',0,[obj('9',.1),obj('8',.3)]))
        self.assertEqual(result['candidates'],[])

    def test_margin_required_in_reverse_direction(self):
        t=tracker();result=t.update(row('a',0,[obj('1',0),obj('2',.2)]),row('b',0,[obj('9',.1)]))
        self.assertEqual(result['candidates'],[])

    def test_same_frame_cross_class_duplicate_sdk_id_rejected(self):
        value=row('a',0,[obj('1'),obj('1',name='person')])
        self.assertEqual(objects(value,'cal'),{})

    def test_same_class_required(self):
        self.assertEqual(tracker().update(row('a',0),row('b',0,[obj('9',name='truck')]))['candidates'],[])

    def test_reused_peer_image_does_not_build_confirmation_count(self):
        t=tracker()
        for index in range(4):result=t.update(row('a',index),row('b',0))
        self.assertEqual(result['associations'],[])

    def test_session_change_retires_prior_lease(self):
        t=tracker();first=confirmed(t)
        self.assertEqual(t.update(row('a',3,session='new'),row('b',3))['associations'],[])
        for index in [4,5]:result=t.update(row('a',index,session='new'),row('b',index))
        self.assertNotEqual(first['mapAssociationId'],result['associations'][0]['mapAssociationId'])

    def test_fusion_epoch_change_clears_and_refuses(self):
        t=tracker();confirmed(t);a=row('a',3);a['fusionEpoch']='new'
        with self.assertRaises(ValueError):t.update(a,row('b',3))
        self.assertFalse(t.leases)

    def test_expired_lease_requires_three_new_fresh_pairs(self):
        t=tracker();first=confirmed(t)
        self.assertEqual(t.update(row('a',60),row('b',60))['associations'],[])
        for index in [61,62]:result=t.update(row('a',index),row('b',index))
        self.assertNotEqual(first['mapAssociationId'],result['associations'][0]['mapAssociationId'])

    def test_competing_member_retires_old_pair(self):
        t=tracker();first=confirmed(t)
        self.assertEqual(t.update(row('a',3),row('b',3,[obj('100')]))['associations'],[])
        self.assertNotIn(('car','1','99'),t.leases)
        for index in [4,5]:result=t.update(row('a',index),row('b',index,[obj('100')]))
        self.assertNotEqual(first['mapAssociationId'],result['associations'][0]['mapAssociationId'])

    def test_class_change_without_new_match_retires_old_pair(self):
        t=tracker();confirmed(t)
        self.assertEqual(t.update(row('a',3,[obj('1',name='person')]),row('b',3))['associations'],[])
        self.assertNotIn(('car','1','99'),t.leases)

    def test_wrong_calibration_and_nonfinite_world_are_refused(self):
        a=row('a',0);a['objects'][0]['native3D']['worldPositionM']=[float('nan'),0]
        self.assertEqual(objects(a,'cal'),{})
        self.assertEqual(objects(row('a',0),'other-cal'),{})


if __name__=='__main__':unittest.main()
