// SPDX-License-Identifier: MIT
import { overviewObservation } from '../overviewObservation';
import type { CityRule, CitySnapshot } from '../types';

const rule: CityRule = { id:'east', sourceId:'sw', name:'East crossing · painted crossing', enabled:true, revision:1, kind:'occupancy-threshold', classes:['person'], conditions:{}, geometry:{space:'image-normalized',points:[[0,0],[1,0],[1,1]]} };
const snapshot = (metric: object, extra: object = {}) => ({ tracks:[], sources:[], events:[], rules:[rule], zones:[], metrics:[{ruleId:rule.id, ...metric}], ...extra }) as CitySnapshot;

it('requires a fresh displayed camera before presenting a finding, and never invents zero', () => {
  expect(overviewObservation(snapshot({status:'active',occupancy:3}), [rule], []).rule).toBeNull();
  expect(overviewObservation(snapshot({status:'unknown',occupancy:3}), [rule], ['sw']).title).not.toContain('3');
  expect(overviewObservation(snapshot({status:'idle'}), [rule], ['sw']).title).not.toContain('0');
  expect(overviewObservation(snapshot({status:'idle',occupancy:0}), [rule], ['sw']).title).toBe('0 people in crossing');
});
it('reports one owner camera and never adds counts from overlapping cameras', () => {
  const other = {...rule,id:'east-ne',sourceId:'ne'};
  const value = overviewObservation(snapshot({status:'active',occupancy:3},{metrics:[{ruleId:rule.id,status:'active',occupancy:3},{ruleId:other.id,status:'active',occupancy:3}]}), [rule,other], ['sw','ne']);
  expect(value.title).toBe('3 people in crossing'); expect(value.rule?.sourceId).toBe('sw');
});
it('names vehicle-only area observations without claiming a stopped event', () => {
  const vehicles = {...rule, id:'stop', kind:'stopped-in-zone', classes:['car','truck','bus']};
  const frame = snapshot({}, {metrics:[{ruleId:'stop',status:'idle',occupancy:1}]});
  expect(overviewObservation(frame,[vehicles],['sw'],'stop').title).toBe('1 vehicle detected in area');
  expect(overviewObservation({...frame,metrics:[{ruleId:'stop',status:'idle',occupancy:2}]},[vehicles],['sw'],'stop').title).toBe('2 vehicles detected in area');
});
it('suppresses the prior finding during a scenario boundary', () => {
  const value = overviewObservation(snapshot({status:'active',occupancy:3},{analyticsScope:{kind:'preparing',epoch:'next',suppressed:true}}),[rule],['sw']);
  expect(value.rule).toBeNull(); expect(value.title).toBe('Preparing the next scene');
});
it('requires current confirmed stop evidence before promoting an event', () => {
  const stopped: CityRule = {...rule,id:'stop',kind:'stopped-in-zone',classes:['car']};
  const event:any = {id:'e',ruleId:'stop',sourceId:'sw',kind:'stopped-in-zone',state:'active',stopEvidenceStatus:'pending'};
  const frame = snapshot({}, {metrics:[{ruleId:'stop',status:'active'}],events:[event]});
  expect(overviewObservation(frame,[stopped],['sw']).event).toBeUndefined();
  expect(overviewObservation({...frame,events:[{...event,stopEvidenceStatus:'confirmed'}]},[stopped],['sw']).title).toBe('Vehicle stopped in crossing');
  expect(overviewObservation({...frame,metrics:[{ruleId:'stop',status:'unknown'} as any],events:[{...event,stopEvidenceStatus:'confirmed'}]},[stopped],['sw']).event).toBeUndefined();
});
