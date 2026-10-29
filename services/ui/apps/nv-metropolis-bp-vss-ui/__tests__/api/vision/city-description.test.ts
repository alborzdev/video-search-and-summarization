// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import handler from '../../../pages/api/vision/city-description';
import { admitWorkload } from '../../../server/vision/workloadAdmissionAdapter';
import { assertSceneScope, validateSceneFrame, sceneDescriptionText } from '../../../server/vision/sceneDescription';
import { observationText } from '../../../server/vision/scenarioObservation';
import { acquireObservationLane, readObservationLane, writeObservationLane } from '../../../server/vision/scenarioObservationLane';
jest.mock('../../../server/vision/scenarioObservationLane', () => ({acquireObservationLane:jest.fn(),readObservationLane:jest.fn(),writeObservationLane:jest.fn(),sharedObservation:jest.fn().mockReturnValue(null)}));
jest.mock('../../../server/vision/workloadAdmissionAdapter', () => ({ admitWorkload: jest.fn(), WorkloadAdmissionError: class extends Error {} }));
jest.mock('../../../server/vision/cosmosReservation', () => ({ withCosmosReservation: (operation: () => Promise<unknown>) => operation(), CosmosReservationError: class extends Error {} }));
const png = Buffer.alloc(33); Buffer.from([137,80,78,71,13,10,26,10]).copy(png); png.write('IHDR',12); png.writeUInt32BE(1280,16); png.writeUInt32BE(480,20);
const frame = () => ({siteId:'site',epoch:'epoch',sourceId:'cam',sessionId:'session',sourceTimeNs:String(BigInt(Date.now()) * BigInt(1000000)),imageBase64:png.toString('base64')});
const report = (f = frame()): any => { const scope = {kind:'normal',epoch:f.epoch,suppressed:false,startedAt:new Date(Date.now()-10000).toISOString()}; return {siteId:f.siteId,mode:'live',analyticsScope:scope,sources:[{id:f.sourceId,sessionId:f.sessionId,status:'live',lastSourceTimeNs:f.sourceTimeNs,analyticsScope:scope}]}; };
const req = (body = frame()) => ({method:'POST',headers:{},body}) as NextApiRequest;
function harness() {
 const state = {status:200,body:null as any}; const res = {setHeader:jest.fn(),status(code:number){state.status=code;return res;},json(body:unknown){state.body=body;return res;}} as unknown as NextApiResponse; return {state,res};
}
const upstream = (body:unknown) => ({ok:true,json:async()=>body});
beforeEach(()=>{
 let locked=false;
 (acquireObservationLane as jest.Mock).mockImplementation(async()=>{if(locked)return null;locked=true;return async()=>{locked=false;};});
 (readObservationLane as jest.Mock).mockResolvedValue({nextAt:0});(writeObservationLane as jest.Mock).mockResolvedValue(undefined);
 (admitWorkload as jest.Mock).mockResolvedValue({decision:'allow',active:{captions:{sourceIds:[]}}});
 global.fetch=jest.fn(async(url)=>String(url).endsWith('/snapshot')?upstream(report()):upstream({model:'cosmos',choices:[{message:{content:'People occupy the crossing.'}}]})) as any;
});
test('sends one PNG with the fixed scene prompt and returns only the final observation',async()=>{
 const {res,state}=harness();await handler(req(),res);expect(state.status).toBe(200);expect(state.body.text).toBe('People occupy the crossing.');
 const sent=JSON.parse((fetch as jest.Mock).mock.calls.find(([url])=>String(url).endsWith('/completions'))![1].body);
 expect(sent.enable_reasoning).toBe(false);expect(sent.messages[0].content[0].image_url.url).toMatch(/^data:image\/png;base64,/);
 expect(sent.messages[0].content[1].text).toMatch(/one sentence/);expect(sent.messages[0].content[1].text).not.toMatch(/four pedestrians|saved report/);
 expect(state.body.imageBase64).toBeUndefined();
});
test('rejects foreign origins and arbitrary URLs/prompts before inference',async()=>{
 const first=harness();await handler({...req(),headers:{origin:'https://outside.example',host:'localhost'}} as NextApiRequest,first.res);expect(first.state.status).toBe(403);
 const second=harness();await handler(req({...frame(),url:'http://other'} as any),second.res);expect(second.state.status).toBe(422);expect(fetch).not.toHaveBeenCalled();
});
test('validates dimensions and refuses a stale, wrong-session or preparing camera frame',()=>{
 const f=frame();expect(validateSceneFrame(f)).toEqual(f);
 expect(()=>validateSceneFrame({...f,imageBase64:Buffer.from([255,216,255]).toString('base64')})).toThrow(/PNG/);
 expect(()=>assertSceneScope(report(f),{...f,sourceTimeNs:'1'})).toThrow();
 expect(()=>assertSceneScope(report(f),{...f,sessionId:'old'})).toThrow();
 expect(()=>assertSceneScope({...report(f),analyticsScope:{...report(f).analyticsScope,kind:'preparing'}},f)).toThrow();
});
test('rejects a result when the scenario changes during inference',async()=>{
 let reads=0;(fetch as jest.Mock).mockImplementation(async(url)=>String(url).endsWith('/snapshot')?upstream(reads++ >= 2?{...report(),analyticsScope:{...report().analyticsScope,epoch:'next'}}:report()):upstream({choices:[{message:{content:'Old observation'}}]}));
 const {res,state}=harness();await handler(req(),res);expect(state.status).toBe(409);expect(state.body.text).toBeUndefined();
});
test('keeps one server inference in flight across tabs without queuing old frames',async()=>{
 let finish!: (value:unknown)=>void; (fetch as jest.Mock).mockImplementation(async(url)=>String(url).endsWith('/snapshot')?upstream(report()):new Promise(resolve=>{finish=resolve;}));
 const first=harness();const pending=handler(req(),first.res);for(let i=0;i<12&&!finish;i++)await Promise.resolve();
 const second=harness();await handler(req(),second.res);expect(second.state.status).toBe(429);
 finish(upstream({choices:[{message:{content:'Current frame'}}]}));await pending;expect(first.state.status).toBe(200);
 expect((fetch as jest.Mock).mock.calls.filter(([url])=>String(url).endsWith('/completions'))).toHaveLength(1);
});
test('does not preempt active captioning and strips reasoning from the UI result',async()=>{
 (admitWorkload as jest.Mock).mockResolvedValue({decision:'allow',active:{captions:{sourceIds:['other']}}});
 const {res,state}=harness();await handler(req(),res);expect(state.status).toBe(429);expect((fetch as jest.Mock).mock.calls.some(([url])=>String(url).endsWith('/completions'))).toBe(false);
 expect(observationText('<think>internal analysis</think><answer>People on the crossing.</answer>')).toBe('People on the crossing.');
 expect(()=>observationText('<think>unfinished')).toThrow();
 expect(sceneDescriptionText('<think>internal analysis</think>Cars are near the crossing. People are on the sidewalk. More detail.')).toBe('Cars are near the crossing. People are on the sidewalk.');
});

test('defers to the shared scenario lane and keeps its crash quarantine',async()=>{
 (readObservationLane as jest.Mock).mockResolvedValue({nextAt:Date.now()+60000});
 const {res,state}=harness();await handler(req(),res);expect(state.status).toBe(429);expect(admitWorkload).not.toHaveBeenCalled();
 expect((fetch as jest.Mock).mock.calls.some(([url])=>String(url).endsWith('/completions'))).toBe(false);
});
test('holds the shared lane until upstream settles and quarantines an uncertain timeout',async()=>{
 (fetch as jest.Mock).mockImplementation(async(url)=>{if(String(url).endsWith('/snapshot'))return upstream(report());throw new Error('Upstream timeout');});
 const warning=jest.spyOn(console,'warn').mockImplementation(()=>{});
 const {res,state}=harness();await handler(req(),res);expect(state.status).toBe(503);
 expect(writeObservationLane).toHaveBeenCalledTimes(1);expect((writeObservationLane as jest.Mock).mock.calls[0][0].nextAt).toBeGreaterThan(Date.now()+50000);
 warning.mockRestore();
});
