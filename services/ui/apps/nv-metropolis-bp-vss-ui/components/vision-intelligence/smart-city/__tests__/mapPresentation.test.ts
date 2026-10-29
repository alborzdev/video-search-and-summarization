// SPDX-License-Identifier: MIT
import {cameraViewCue, monitoringDescription} from '../mapPresentation';
import type {CitySource, CityRule} from '../types';
const source: CitySource = {id:'camera',name:'Camera',width:960,height:540,calibrationRevision:'current',imageToGroundHomography:[[1,0,0],[0,1,0],[0,0,1]],cameraPositionWorldM:[0,0,8],groundCoverageM:[[10,-5],[20,-5],[20,5],[10,5]],T_cv_from_site:[[0,1,0,0],[0,0,1,0],[1,0,0,0],[0,0,0,1]]};
describe('map camera cues and area descriptions',()=>{
 it('keeps exported coverage intact and builds a bounded view-direction fan from its calibrated rays',()=>{
  const cue=cameraViewCue(source,4)!; expect(cue.coverage).toBe(source.groundCoverageM); expect(cue.heading).toBe(0); expect(cue.origin).toEqual([0,0]);
  expect(cue.cone[0]).toEqual([0,0]); for(const [x,y] of cue.cone.slice(1)){expect(Math.hypot(x,y)).toBeCloseTo(4);expect(x).toBeGreaterThan(0);}
  expect(Math.atan2(cue.cone[1][1],cue.cone[1][0])).toBeCloseTo(Math.atan2(-5,10));
 });
 it('does not invent a camera cue for missing or invalid calibration',()=>{
  expect(cameraViewCue({...source,calibrationRevision:undefined},4)).toBeNull(); expect(cameraViewCue({...source,groundCoverageM:[[0,0],[NaN,2],[3,4]]},4)).toBeNull();
 });
 it('explains configured detection classes and timing instead of inventing current measurements',()=>{
  const rule={kind:'stopped-in-zone',classes:['car','bus'],conditions:{minimumDurationMs:5000}} as CityRule;
  expect(monitoringDescription(rule)).toBe('Checks for cars and buses stopped in this area for at least 5 seconds.');
  expect(monitoringDescription({...rule,kind:'line-crossing',classes:['person']})).toBe('Counts people that cross this line in the configured direction.');
 });
});
