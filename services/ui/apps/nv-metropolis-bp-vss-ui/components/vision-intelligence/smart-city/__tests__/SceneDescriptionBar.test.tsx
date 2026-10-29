// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { SceneDescriptionBar } from '../SceneDescriptionBar';
import { captureSceneFrame } from '../scenarioFrameCapture';
jest.mock('../scenarioFrameCapture', () => ({ captureSceneFrame: jest.fn() }));
const props = { siteId:'site', epoch:'epoch', sourceId:'cam', sessionId:'session', sourceName:'Southwest corner', enabled:true };
const response = (frame:any, text='Vehicles are near the junction.') => ({ ok:true, json:async()=>({ ...frame, imageBase64:undefined, text,
  observedAt:new Date(Number(BigInt(frame.sourceTimeNs)/BigInt(1000000))).toISOString(), model:'cosmos', inferenceMs:1200 }) });
beforeEach(() => {
  jest.useFakeTimers();
  (captureSceneFrame as jest.Mock).mockImplementation(identity=>({ ...identity, sourceTimeNs:String(BigInt(Date.now())*BigInt(1000000)), imageBase64:'png' }));
  global.fetch=jest.fn(async(_url,init)=>response(JSON.parse(init!.body as string))) as any;
});
afterEach(()=>jest.useRealTimers());
test('only describes on click, puts the answer in the bar, and never polls the model', async()=>{
  render(<SceneDescriptionBar {...props}/>);
  await act(async()=>{jest.advanceTimersByTime(30000);}); expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Describe scene'})); await act(async()=>{});
  expect(screen.getByText('Vehicles are near the junction.')).toBeInTheDocument();
  expect(screen.getByText(/Cosmos VLM · Southwest corner · captured/)).toBeInTheDocument();
  await act(async()=>{jest.advanceTimersByTime(30000);}); expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button',{name:'Describe scene'})); await act(async()=>{}); expect(fetch).toHaveBeenCalledTimes(2);
});
test('disables repeat clicks while busy and discards results from a changed scene',async()=>{
  let finish!:(value:unknown)=>void; let sent:any;
  (fetch as jest.Mock).mockImplementation((_url,init)=>{sent=JSON.parse(init.body);return new Promise(resolve=>{finish=resolve;});});
  const {rerender}=render(<SceneDescriptionBar {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Describe scene'}));
  expect(screen.getByRole('button',{name:'Describing…'})).toBeDisabled();
  rerender(<SceneDescriptionBar {...props} epoch="new"/>);
  await act(async()=>finish(response(sent,'Old scene answer')));
  expect(screen.queryByText('Old scene answer')).not.toBeInTheDocument();expect(fetch).toHaveBeenCalledTimes(1);
});
test('retries local frame matching without extra model calls and stops when disabled',async()=>{
  (captureSceneFrame as jest.Mock).mockReturnValueOnce(null);
  const {rerender}=render(<SceneDescriptionBar {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Describe scene'}));expect(fetch).not.toHaveBeenCalled();
  await act(async()=>{jest.advanceTimersByTime(250);});expect(fetch).toHaveBeenCalledTimes(1);
  rerender(<SceneDescriptionBar {...props} enabled={false}/>);
  expect(screen.getByRole('button',{name:'Describe scene'})).toBeDisabled();
});
test('a busy response allows a manual retry without scheduling another inference',async()=>{
  (fetch as jest.Mock).mockResolvedValueOnce({ok:false,json:async()=>({error:'VLM is busy. Try again.'})});
  render(<SceneDescriptionBar {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Describe scene'}));await act(async()=>{});
  expect(screen.getByText('VLM is busy. Try again.')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Describe scene'})).toBeEnabled();
  await act(async()=>{jest.advanceTimersByTime(30000);});expect(fetch).toHaveBeenCalledTimes(1);
});
