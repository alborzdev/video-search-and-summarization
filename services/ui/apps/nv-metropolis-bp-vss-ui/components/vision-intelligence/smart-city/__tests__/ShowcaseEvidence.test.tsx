// SPDX-License-Identifier: MIT
import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { ShowcaseEvidence, showcaseMatches, validShowcaseMeasurement } from '../ShowcaseEvidence';
import type { CitySite, AnalyticsScope } from '../types';
const scope: AnalyticsScope = {kind:'scenario',epoch:'epoch',runId:'run',scenarioId:'crossing-occupancy',startedAt:'2026-10-29T00:00:00Z',suppressed:false};
const site = {id:'site',mode:'live',sources:[{id:'cam'}]} as CitySite;
const row = {ruleId:'expo-crossing-occupancy',sourceId:'cam',sessionId:'session',name:'East crossing',status:'occupied' as const,count:4,peakCount:4,occupiedSeconds:3.2,continuousSeconds:3.2,hasGaps:false,asOfSourceTimeNs:String(BigInt(Date.parse(scope.startedAt!))*BigInt(1000000)),savedEventIds:['saved-id']};
const report = {siteId:'site',mode:'live',analyticsScope:scope,measurements:[row]};
beforeEach(()=>{global.fetch=jest.fn().mockResolvedValue({ok:true,json:async()=>report});});
afterEach(()=>jest.useRealTimers());
test('renders source observations and a durable event, without a scripted actor count', async()=>{
 render(<ShowcaseEvidence site={site} scenarioId="crossing-occupancy" currentScope={scope}/>);
 await screen.findByText('Crossing occupied');
 expect(screen.getAllByText('4')).toHaveLength(2);
 expect(screen.getByText('✓ Camera event saved')).toBeInTheDocument();
 expect(screen.getByText('3.2 s')).toBeInTheDocument();
});
test('scope, session data and bounded metrics must be valid',()=>{
 expect(showcaseMatches(report,site,scope)).toBe(true);
 expect(showcaseMatches({...report,analyticsScope:{...scope,runId:'old'}},site,scope)).toBe(false);
 expect(showcaseMatches(report,site,{...scope,suppressed:true})).toBe(false);
 expect(validShowcaseMeasurement({...row,occupiedSeconds:NaN})).toBe(false);
 expect(validShowcaseMeasurement({...row,count:-1})).toBe(false);
});
test('removes stale live numbers when requests stop arriving and never runs the camera timer on the wall clock',async()=>{
 jest.useFakeTimers();render(<ShowcaseEvidence site={site} scenarioId="crossing-occupancy" currentScope={scope}/>);
 await act(async()=>{}); expect(screen.getByText('Crossing occupied')).toBeInTheDocument();
 (fetch as jest.Mock).mockRejectedValue(new Error('offline'));
 await act(async()=>{jest.advanceTimersByTime(3500);});
 expect(screen.getByText('Waiting for camera evidence')).toBeInTheDocument();
 expect(screen.queryByText('3.2 s')).not.toBeInTheDocument();
});
test('shows the buildup, confirmed blockage, and clearance only from current camera evidence',async()=>{
 jest.useFakeTimers();
 const vehicleScope={...scope,scenarioId:'queue-blockage'};
 const junction={...row,ruleId:'expo-junction-blockage',status:'clear',count:0,peakCount:0,occupiedSeconds:0,continuousSeconds:0,savedEventIds:[] as string[]};
 const queue={...junction,ruleId:'expo-approach-queue'};
 const evidence={...report,analyticsScope:vehicleScope,measurements:[junction,queue]};
 (fetch as jest.Mock).mockImplementation(async()=>({ok:true,json:async()=>evidence}));
 render(<ShowcaseEvidence site={site} scenarioId="queue-blockage" currentScope={vehicleScope}/>);
 await act(async()=>{});expect(screen.getByText('Junction clear')).toBeInTheDocument();
 junction.status='unknown';
 await act(async()=>{jest.advanceTimersByTime(700);});expect(screen.getByText('Checking for blockage')).toBeInTheDocument();
 junction.status='clear';
 queue.count=3;queue.peakCount=3;queue.status='occupied';
 await act(async()=>{jest.advanceTimersByTime(700);});expect(screen.getByText('Junction clear')).toBeInTheDocument();
 expect(screen.queryByText('Approach queue detected')).not.toBeInTheDocument();
 expect(screen.queryByText('Junction blocked')).not.toBeInTheDocument();
 junction.count=2;junction.peakCount=2;junction.status='occupied';junction.savedEventIds=['camera-event'];
 await act(async()=>{jest.advanceTimersByTime(700);});expect(screen.getByText('Junction blocked')).toBeInTheDocument();
 expect(screen.getByText('peak stopped')).toBeInTheDocument();
 expect(screen.getByText('✓ Camera event saved')).toBeInTheDocument();
 junction.count=0;junction.status='clear';
 await act(async()=>{jest.advanceTimersByTime(700);});expect(screen.getByText('Junction cleared')).toBeInTheDocument();
});
