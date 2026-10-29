// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { ScenarioVlmObservation } from '../ScenarioVlmObservation';
import { captureScenarioFrame } from '../scenarioFrameCapture';
jest.mock('../scenarioFrameCapture',()=>({captureScenarioFrame:jest.fn()}));
const props={siteId:'site',scenarioId:'crossing-occupancy',epoch:'epoch',runId:'run',sourceId:'cam',sessionId:'session',enabled:true};
const response=(frame:any,text='People occupy the crossing.')=>({ok:true,json:async()=>({...frame,imageBase64:undefined,text,observedAt:new Date(Number(BigInt(frame.sourceTimeNs)/BigInt(1000000))).toISOString(),inferenceMs:1200,model:'cosmos'})});
beforeEach(()=>{
 jest.useFakeTimers();(captureScenarioFrame as jest.Mock).mockImplementation(identity=>({...identity,sourceTimeNs:String(BigInt(Date.now())*BigInt(1000000)),imageBase64:'png'}));
 global.fetch=jest.fn(async(_url,init)=>response(JSON.parse(init!.body as string))) as any;
});
afterEach(()=>jest.useRealTimers());
test('starts only after an event, updates at three-second cadence, and pauses',async()=>{
 const {rerender}=render(<ScenarioVlmObservation {...props} enabled={false}/>);await act(async()=>{});expect(fetch).not.toHaveBeenCalled();
 rerender(<ScenarioVlmObservation {...props}/>);await act(async()=>{});expect(screen.getByText('People occupy the crossing.')).toBeInTheDocument();expect(fetch).toHaveBeenCalledTimes(1);
 await act(async()=>{jest.advanceTimersByTime(3000);});expect(fetch).toHaveBeenCalledTimes(2);
 fireEvent.click(screen.getByRole('button',{name:'Pause VLM observations'}));await act(async()=>{jest.advanceTimersByTime(9000);});expect(fetch).toHaveBeenCalledTimes(2);
 fireEvent.click(screen.getByRole('button',{name:'Resume VLM observations'}));await act(async()=>{});expect(fetch).toHaveBeenCalledTimes(3);
});
test('never overlaps slow requests and ignores an old run after a switch',async()=>{
 let finish!: (value:unknown)=>void;let sent:any;(fetch as jest.Mock).mockImplementation((_url,init)=>{sent=JSON.parse(init.body);return new Promise(resolve=>{finish=resolve;});});
 const {rerender}=render(<ScenarioVlmObservation {...props}/>);await act(async()=>{jest.advanceTimersByTime(9000);});expect(fetch).toHaveBeenCalledTimes(1);
 const old=sent;const oldFinish=finish;rerender(<ScenarioVlmObservation {...props} epoch="new" enabled={false}/>);
 await act(async()=>{oldFinish(response(old,'Old run answer'));});expect(screen.queryByText('Old run answer')).not.toBeInTheDocument();
});
test('does not send unmatched camera pixels and stops in a hidden tab',async()=>{
 (captureScenarioFrame as jest.Mock).mockReturnValue(null);render(<ScenarioVlmObservation {...props}/>);await act(async()=>{});expect(fetch).not.toHaveBeenCalled();expect(screen.getByText('Waiting for a fresh camera frame…')).toBeInTheDocument();
 Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});fireEvent(document,new Event('visibilitychange'));
 await act(async()=>{jest.advanceTimersByTime(9000);});expect(fetch).not.toHaveBeenCalled();
 Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
});
test('retries a local metadata gap promptly without speeding up model requests',async()=>{
 (captureScenarioFrame as jest.Mock).mockReturnValueOnce(null);
 render(<ScenarioVlmObservation {...props}/>);await act(async()=>{});expect(fetch).not.toHaveBeenCalled();
 await act(async()=>{jest.advanceTimersByTime(250);});expect(fetch).toHaveBeenCalledTimes(1);
 await act(async()=>{jest.advanceTimersByTime(1000);});expect(fetch).toHaveBeenCalledTimes(1);
});
