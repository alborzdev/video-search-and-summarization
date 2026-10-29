// SPDX-License-Identifier: MIT
import {areaInCamera,clipGroundArea,groundAreaHighlight} from '../areaProjection';
import type {CityRule,CitySource} from '../types';
const camera:CitySource={id:'b',name:'B',width:100,height:100,calibrationRevision:'current',imageToGroundHomography:[[1,0,0],[0,1,0],[0,0,1]],groundCoverageM:[[0,0],[100,0],[100,100],[0,100]]};
describe('cross-camera area guides',()=>{
 it('clips partially visible polygons and directed lines to the target ground view',()=>{
  expect(clipGroundArea([[-10,10],[20,10]],camera.groundCoverageM!)).toEqual([[0,10],[20,10]]);
  const points=areaInCamera({id:'zone',name:'Zone',sourceId:'a',points:[[-20,20],[20,20],[20,80],[-20,80]]},camera);
  expect(points).toEqual([[0,.2],[.2,.2],[.2,.8],[0,.8]]);
  expect(clipGroundArea([[-10,10],[20,10]],[...camera.groundCoverageM!].reverse())).toEqual([[0,10],[20,10]]);
 });
 it('omits areas outside the view and does not invent calibration or project through a singular matrix',()=>{
  const area={id:'zone',name:'Zone',sourceId:'a',points:[[110,10],[150,10]] as [number,number][]};
  expect(areaInCamera(area,camera)).toEqual([]);expect(areaInCamera(area,{...camera,groundCoverageM:undefined})).toEqual([]);
  expect(areaInCamera(area,{...camera,imageToGroundHomography:[[0,0,0],[0,0,0],[0,0,0]]})).toEqual([]);
 });
 it('lifts an owned rule to world coordinates only with matching source calibration',()=>{
  const rule={id:'zone',name:'Zone',sourceId:'b',enabled:true,classes:['person'],calibrationRevision:'current',geometry:{space:'image-normalized',points:[[.1,.2],[.8,.9]]}} as CityRule;
  expect(groundAreaHighlight(rule,[camera])?.points).toEqual([[10,20],[80,90]]);
  expect(groundAreaHighlight({...rule,calibrationRevision:'old'},[camera])).toBeNull();
 });
});
