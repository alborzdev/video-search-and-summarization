# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate_tracking_quality import Reference, evaluate, image_assignment


def setup():
    actors = [dict(referenceId='actor-a', className='car', primPath='/a', worldPositionM=[10, 10, 0]),
              dict(referenceId='actor-b', className='car', primPath='/b', worldPositionM=[30, 10, 0])]
    def sample(ns):
        return dict(sampleStartUnixNs=str(ns), sampleEndUnixNs=str(ns+2), stageId='s', vehicleGeneration=1,
            trafficGeneration=1, peopleGeneration=1, playing=True, scenario=dict(active=False, state='idle'), errors=[], objects=deepcopy(actors))
    samples = [sample(1_000_000_000), sample(1_200_000_000)]
    export = dict(groundWorldZM=0, cameras={'one': dict(projectionMatrix3x4=[[1,0,0,0],[0,1,0,0],[0,0,0,1]]),
                                          'two': dict(projectionMatrix3x4=[[1,0,0,0],[0,1,0,0],[0,0,0,1]])})
    package = dict(classGeometry=[dict(className='car', heightM=2, measurements=[])])
    package['classGeometry'][0]['class'] = package['classGeometry'][0].pop('className')
    def row(source, x=10, native_id='7', world_x=10):
        return dict(sourceId=source, sourceSessionId=source+'session', fusionEpoch='epoch', sourceFrameId='1',
            sourceTimeNs='1100000000', timestampBasis='recorded-native-sei', rawSourcePtsNs='123',
            sourceClockEvidence=dict(captureTimeNs='1100000000', auPtsNs='123'),
            detectorTrackerAudit=dict(inputSnapshotComplete=True, inputDetectionCount=1,
                inputs=[dict(ordinal=1, sdkClassId=2, bboxPx=[x-2,8,4,4])],
                outputs=[dict(currentDetectorStamp=True, untracked=False, idRejectedAsAmbiguous=False, inputOrdinal=1, sdkTargetId=native_id)]),
            objects=[dict(localTrackId=native_id, observedThisFrame=True, **{'class':'car'},
                native3D=dict(worldPositionM=[world_x,10], visibility=.9))])
    return samples, export, package, row


def test_world_estimate_cannot_choose_a_convenient_reference():
    samples, export, package, row = setup()
    output = evaluate([row('a', world_x=30), row('b', world_x=30)], samples, export, package, dict(a='one', b='two'))
    assert output['offsetsMs']['0']['nativePositionErrorM']['car']['p50'] == 20


def test_same_native_id_on_different_image_actors_is_a_wrong_join():
    samples, export, package, row = setup()
    output = evaluate([row('a'), row('b', x=30, world_x=30)], samples, export, package, dict(a='one', b='two'))
    assert output['offsetsMs']['0']['byClass']['all']['wrongSharedIdPairs'] == 1


def test_missing_native_outputs_still_count_as_co_detected_opportunities():
    samples, export, package, row = setup()
    a,b = row('a'),row('b'); b['objects'] = []
    output = evaluate([a,b], samples, export, package, dict(a='one', b='two'))['offsetsMs']['0']['byClass']['car']
    assert output['coDetectedActorPairs'] == 1
    assert output['pairMissingObservedTrack'] == 1
    assert output['missingObservedTrack'] == 1


def test_reference_never_extrapolates_or_crosses_generation_boundaries():
    samples, export, package, _ = setup()
    reference = Reference(samples, export, package['classGeometry'])
    assert reference.actors(900_000_000) is None
    samples[1]['trafficGeneration'] = 2
    assert reference.actors(1_100_000_000) is None


def test_image_overlap_is_unknown_even_with_a_good_world_estimate():
    actors = [({'referenceId':name,'className':'car'}, [[10,10],[10,10]]) for name in ('a','b')]
    assert image_assignment([8,8,4,4], 'car', actors) == (None, 'ambiguous-image')


def test_position_bias_is_distinct_from_frame_to_frame_jitter():
    samples, export, package, row = setup()
    values = [row('a', world_x=30), row('b', world_x=30)]
    for source in ('a','b'):
        second = row(source, world_x=31)
        second.update(sourceTimeNs='1150000000', sourceFrameId='2', rawSourcePtsNs='124',
            sourceClockEvidence=dict(captureTimeNs='1150000000',auPtsNs='124'))
        values.append(second)
    result = evaluate(values, samples, export, package, dict(a='one',b='two'))['offsetsMs']['0']
    assert result['nativePositionErrorM']['car']['p50'] >= 20
    assert result['nativePositionResidualStepM']['car']['p50'] == 1


def test_one_camera_reusing_an_id_for_another_image_actor_is_not_continuity():
    samples, export, package, row = setup()
    for next_id, expected in (('7', 1), ('8', 0)):
        values = [row('a'), row('b')]
        second = row('a', x=30, world_x=30, native_id=next_id)
        second.update(sourceTimeNs='1150000000', sourceFrameId='2', rawSourcePtsNs='124',
            sourceClockEvidence=dict(captureTimeNs='1150000000', auPtsNs='124'))
        values.append(second)
        result = evaluate(values, samples, export, package, dict(a='one', b='two'))['offsetsMs']['0']
        assert result['byClass'].get('all', {}).get('withinCameraReferenceSwitches', 0) == expected


def test_live_measurement_keeps_its_original_clock_basis():
    samples, export, package, row = setup()
    rows = [row('a'), row('b')]
    for item in rows:
        item['timestampBasis'] = 'source-native-sei'
    try:
        evaluate(rows, samples, export, package, dict(a='one', b='two'))
    except ValueError:
        pass
    else:
        raise AssertionError('Live observations must not be mistaken for recorded replay')
    result = evaluate(rows, samples, export, package, dict(a='one', b='two'), clock_basis='source-native-sei')
    assert result['clockBasis'] == 'source-native-sei'
