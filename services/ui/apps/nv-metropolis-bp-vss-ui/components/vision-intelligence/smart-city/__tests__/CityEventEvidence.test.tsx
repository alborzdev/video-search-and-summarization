// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { CityEventEvidence, cityEventWindow } from '../CityEventEvidence';
const source: any = { id:'camera-a', vssSensorId:'sensor-a', name:'Southwest', mode:'live' };
const event: any = { id:'event-a', mode:'live', sourceId:'camera-a', evidence:{sourceId:'camera-a',startTimeNs:'1793078703987032651',endTimeNs:'1793078713987032651'} };
// An actual same-origin evidence route URL, with no arbitrary remote host.
const response = {ok:true,json:async()=>({startTime:cityEventWindow(event,source)!.startTime,videoUrl:'http://video.test/vst/storage/temp_files/clip.mp4'})};
const props = {event,source,vstApiUrl:'http://video.test/vst/api'};
afterEach(()=>jest.restoreAllMocks());
test('requires the declared source and bounded nanosecond interval without guessing times',()=>{
 expect(cityEventWindow(event,source)?.durationSeconds).toBe(10);
 for(const changed of [{...event,mode:'fixture-replay'},{...event,sourceId:'other'},{...event,evidence:{...event.evidence,startTimeNs:1793078703987032651}},{...event,evidence:{...event.evidence,endTimeNs:'1793078703987032651'}},{...event,evidence:{...event.evidence,endTimeNs:'1793080003987032651'}}]) expect(cityEventWindow(changed,source)).toBeNull();
 expect(cityEventWindow(event,{...source,id:'other'})).toBeNull();
});
test('requests only the chosen event interval after an explicit action',async()=>{
 global.fetch=jest.fn().mockResolvedValue(response);render(<CityEventEvidence {...props}/>);expect(fetch).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Review event footage'}));await screen.findByLabelText('Event footage from Southwest');
 const url=(fetch as jest.Mock).mock.calls[0][0];expect(url).toContain('sensorId=sensor-a');expect(decodeURIComponent(url)).toContain(cityEventWindow(event,source)!.startTime);
});
test('rejects mismatched timing and unsupported URLs',async()=>{
 global.fetch=jest.fn().mockResolvedValueOnce({ok:true,json:async()=>({startTime:'2020-01-01',videoUrl:'http://video.test/vst/storage/temp_files/clip.mp4'})}).mockResolvedValue({ok:true,json:async()=>({videoUrl:'https://outside.test/clip.mp4'})});
 render(<CityEventEvidence {...props}/>);fireEvent.click(screen.getByRole('button',{name:'Review event footage'}));expect(await screen.findByRole('alert')).toHaveTextContent('different event interval');
 fireEvent.click(screen.getByRole('button',{name:'Review event footage'}));expect(await screen.findByRole('alert')).toHaveTextContent('URL is not supported');
});
test('a late response cannot replace a newly selected event',async()=>{
 let finish!:(v:unknown)=>void;global.fetch=jest.fn(()=>new Promise(resolve=>{finish=resolve;}));
 const {rerender}=render(<CityEventEvidence {...props}/>);fireEvent.click(screen.getByRole('button',{name:'Review event footage'}));
 rerender(<CityEventEvidence {...props} event={{...event,id:'event-b'}}/>);await act(async()=>finish(response));expect(screen.queryByLabelText('Event footage from Southwest')).toBeNull();
});
test('rejects a full recording masquerading as the requested interval',async()=>{
 global.fetch=jest.fn().mockResolvedValue(response);jest.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});
 render(<CityEventEvidence {...props}/>);fireEvent.click(screen.getByRole('button',{name:'Review event footage'}));const video=await screen.findByLabelText('Event footage from Southwest');Object.defineProperty(video,'duration',{value:91});fireEvent.loadedMetadata(video);expect(screen.getByRole('alert')).toHaveTextContent('duration does not match');
});
test('times out and permits a deliberate retry',async()=>{
 jest.useFakeTimers();try{global.fetch=jest.fn((_url,init)=>new Promise((_resolve,reject)=>init!.signal!.addEventListener('abort',()=>reject(new Error('abort')))));
 const {unmount}=render(<CityEventEvidence {...props}/>);fireEvent.click(screen.getByRole('button',{name:'Review event footage'}));await act(async()=>{jest.advanceTimersByTime(90000);});expect(screen.getByRole('alert')).toHaveTextContent('timed out');expect(screen.getByRole('button',{name:'Review event footage'})).toBeEnabled();unmount();}finally{jest.useRealTimers();}
});
