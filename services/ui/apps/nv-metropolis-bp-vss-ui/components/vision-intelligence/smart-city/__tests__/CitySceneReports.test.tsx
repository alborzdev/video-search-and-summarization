// SPDX-License-Identifier: MIT
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { archivedFinding, archivedScene, CitySceneReports, type ArchivedScene } from '../CitySceneReports';
import type { CityEvent, CitySite } from '../types';
import type { MobilityReport } from '../mobilityTypes';
import { cityRequest } from '../useCity';
jest.mock('../useCity', () => ({ cityRequest: jest.fn() }));
const site: CitySite = { id:'site',name:'Site',revision:20,mode:'live',sources:[{id:'sw',name:'Southwest corner',width:960,height:540}],map:{bounds:[0,0,10,10],roads:[],buildings:[]} };
const report: MobilityReport = {schemaVersion:'city.mobility.v1',siteId:'site',siteRevision:10,mode:'live',configRevision:2,windowMinutes:5,timeBasis:'per-camera-source-time',globalFusionEnabled:false,
 config:{revision:2,movements:[],crossings:[],queues:[],curbs:[]},coverage:[{sourceId:'sw',name:'Southwest',status:'live',windowStartNs:'1793080800000000000',windowEndNs:'1793080825000000000',timestampBasis:'source-native-sei',observedSeconds:20,windowSeconds:300,coverageRatio:20/300,truncated:false}],lineCounts:[],movements:[],queues:[],crossings:[],curbs:[],configurationIssues:[],limitations:['Camera-owned measures.'],
 obstructions:[{ruleId:'cam_sw-blocked-crossing',name:'South crossing',sourceId:'sw',episodeCount:1,completedEpisodes:0,ongoingEpisodes:1,unknownEpisodes:0,blockedSeconds:9.2,longestObservedEpisodeSeconds:9.2,eventIds:['event'],status:'partial'}]};
const scene: ArchivedScene = {epoch:'epoch-a',kind:'scenario',runId:'run-a',scenarioId:'crossing-obstruction',startedAt:'2026-10-27T06:00:00Z',endedAt:'2026-10-27T06:00:25Z',mobilitySnapshotBasis:'last-observed-before-boundary',mobility:report};
const event: CityEvent = { id:'event',ruleId:'cam_sw-blocked-crossing',ruleName:'South crossing',kind:'stopped-in-zone',sourceId:'sw',sessionId:'session',trackIds:['1'],state:'unknown',startedAt:scene.startedAt,triggeredAt:scene.startedAt,message:'Observed stop',metrics:{},mode:'live',analyticsScope:{kind:'scenario',epoch:scene.epoch,runId:scene.runId,scenarioId:scene.scenarioId},evidence:{status:'available',sourceId:'sw',startTimeNs:'1793080800000000000',endTimeNs:'1793080810000000000'} };
afterEach(()=>jest.resetAllMocks());
test('accepts historical revisions only for this site and explicit closed scenario evidence',()=>{
 expect(archivedScene(scene,site)).toBe(true);
 for(const value of [{...scene,kind:'normal'},{...scene,endedAt:'invalid'},{...scene,endedAt:'2026-10-26T00:00:00Z'},{...scene,mobilitySnapshotBasis:'example'},{...scene,mobility:{...report,siteId:'another'}},{...scene,mobility:{...report,globalFusionEnabled:true}},{...scene,mobility:{...report,obstructions:[null]}},{...scene,mobility:{...report,obstructions:[{...report.obstructions[0],sourceId:'foreign'}]}}]) expect(archivedScene(value,site)).toBe(false);
});
test('does not turn an ongoing final observation into a cleared episode or fill missing measures with zero',()=>{
 const f=archivedFinding(scene); expect(f.value).toBe('9.2 s'); expect(f.facts).toContainEqual(['Ongoing at observation end','1']); expect(f.facts).toContainEqual(['Completed episodes','0']);
 expect(archivedFinding({...scene,mobility:{...report,obstructions:[]}}).value).toBe('—');
 expect(archivedFinding({...scene,mobility:{...report,coverage:[]}}).value).toBe('—');
});
test('links only a matching run event with a registered, valid evidence interval',async()=>{
 (cityRequest as jest.Mock).mockImplementation(path=>Promise.resolve(path==='analytics-scopes'?{prior:[scene]}:{events:[{...event,id:'wrong-run',analyticsScope:{...event.analyticsScope,epoch:'different'}},event]}));
 const onReviewEvent=jest.fn();render(<CitySceneReports site={site} onReviewEvent={onReviewEvent}/>);
 await screen.findByText('9.2 s');expect(screen.getByText('Recorded scene · Not live')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Review a camera event'}));await waitFor(()=>expect(onReviewEvent).toHaveBeenCalledWith(event));
});
test('never substitutes current footage when no report event interval exists',async()=>{
 (cityRequest as jest.Mock).mockImplementation(path=>Promise.resolve(path==='analytics-scopes'?{prior:[scene]}:{events:[{...event,evidence:{...event.evidence,sourceId:'different'}}]}));
 const onReviewEvent=jest.fn();render(<CitySceneReports site={site} onReviewEvent={onReviewEvent}/>);await screen.findByText('9.2 s');fireEvent.click(screen.getByRole('button',{name:'Review a camera event'}));await screen.findByText(/No retained event interval/);expect(onReviewEvent).not.toHaveBeenCalled();
});
test('site changes clear historical results before the next request completes',async()=>{
 (cityRequest as jest.Mock).mockResolvedValueOnce({prior:[scene]}).mockImplementation(()=>new Promise(()=>{}));
 const {rerender}=render(<CitySceneReports site={site} onReviewEvent={jest.fn()}/>);await screen.findByText('9.2 s');rerender(<CitySceneReports site={{...site,id:'other'}} onReviewEvent={jest.fn()}/>);expect(screen.queryByText('9.2 s')).not.toBeInTheDocument();
});

test('retains source-observed showcase totals and never invents a zero for a missing run',()=>{
 const showcase = [{ruleId:'expo-crossing-occupancy',sourceId:'sw',sessionId:'s',name:'East crossing',status:'clear' as const,count:0,peakCount:4,occupiedSeconds:13.5,continuousSeconds:0,hasGaps:true,asOfSourceTimeNs:'1793080825000000000',savedEventIds:['event']}];
 const value={...scene,scenarioId:'crossing-occupancy',showcase};
 expect(archivedScene(value,site)).toBe(true);
 expect(archivedScene({...value,showcase:[{...showcase[0],sourceId:'foreign'}]},site)).toBe(false);
 expect(archivedFinding(value).value).toBe('13.5 s');
 expect(archivedFinding(value).facts).toContainEqual(['Peak people in crossing','4']);
 expect(archivedFinding({...value,showcase:[]}).value).toBe('—');
});
