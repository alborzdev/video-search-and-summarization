# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluate_vehicle_ground_truth import ground_class, interpolate, match, normal


def sample(time_ns,position=0,active=False,generation=1):
    return {'sampleStartUnixNs':str(time_ns),'sampleEndUnixNs':str(time_ns),'playing':True,'errors':[],
            'stageId':'stage','controllerGeneration':generation,'trafficGeneration':0,
            'scenario':{'active':active,'classicState':None},
            'vehicles':[{'arrivalId':1,'asset':'car_sedan.usdc','simulationClass':'car','primPath':'/car',
                         'worldPositionM':[position,0,0],'modelToActualWorldErrorM':0,
                         'scenarioOwner':'','scenarioHeld':False}]}


class VehicleTruthTests(unittest.TestCase):
    def test_interpolation_uses_actual_world_wall_time(self):
        actors,reason=interpolate([sample(0),sample(400_000_000,2)],[0,400_000_000],200_000_000)
        self.assertIsNone(reason);self.assertEqual(actors[0]['positionM'],[1,0,0])

    def test_no_extrapolation_or_long_gap(self):
        self.assertEqual(interpolate([sample(0),sample(600_000_000)],[0,600_000_000],-1)[1],'unbracketed')
        self.assertEqual(interpolate([sample(0),sample(600_000_000)],[0,600_000_000],100_000_000)[1],'GT-gap')

    def test_staged_and_generation_changed_are_refused(self):
        self.assertEqual(interpolate([sample(0),sample(400_000_000,active=True)],[0,400_000_000],200_000_000)[1],'staged-or-invalid-GT')
        self.assertEqual(interpolate([sample(0),sample(400_000_000,generation=2)],[0,400_000_000],200_000_000)[1],'GT-generation-change')

    def test_spawn_despawn_does_not_invent_a_continuous_actor(self):
        a,b=sample(0),sample(400_000_000);b['vehicles'][0]['arrivalId']=2
        actors,reason=interpolate([a,b],[0,400_000_000],200_000_000)
        self.assertIsNone(reason);self.assertEqual(actors,[])

    def test_nearest_wrong_class_cannot_be_skipped(self):
        actors=[{'arrivalId':1,'class':'truck','positionM':[0,0,0],'asset':'pickup'},
                {'arrivalId':2,'class':'car','positionM':[1.5,0,0],'asset':'sedan'}]
        self.assertEqual(match([0,0],'car',actors)[1],'class-mismatch')

    def test_exact_two_metres_allowed_beyond_refused(self):
        actors=[{'arrivalId':1,'class':'car','positionM':[0,0,0],'asset':'sedan'}]
        self.assertIsNotNone(match([2,0],'car',actors)[0])
        self.assertEqual(match([2.00001,0],'car',actors)[1],'beyond-2m')

    def test_runner_up_margin_and_asset_class_mapping(self):
        actors=[{'arrivalId':1,'class':'car','positionM':[0,0,0],'asset':'sedan'},
                {'arrivalId':2,'class':'car','positionM':[.9,0,0],'asset':'sedan'}]
        self.assertEqual(match([0,0],'car',actors)[1],'margin-below-1m')
        self.assertEqual(ground_class({'asset':'/absolute/car_pickup.usdc','simulationClass':'car'}),'truck')
        self.assertEqual(ground_class({'asset':'car_sedan.usdc','simulationClass':'car'}),'car')


if __name__=='__main__':unittest.main()
