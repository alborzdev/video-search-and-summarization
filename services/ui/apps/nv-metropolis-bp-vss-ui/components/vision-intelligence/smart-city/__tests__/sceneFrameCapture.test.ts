// SPDX-License-Identifier: MIT
import { captureSceneFrame, captureScenarioFrame, registerScenarioCamera } from '../scenarioFrameCapture';
import type { CityVideoFrame } from '../types';
const identity = {siteId:'site',epoch:'epoch',sourceId:'cam',sessionId:'session'};
test('captures a full camera frame without overlays or an event, preserving aspect ratio',()=>{
  const video = document.createElement('video');
  Object.defineProperties(video,{videoWidth:{value:1920},videoHeight:{value:720}});
  const drawImage=jest.fn();const context=jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage} as any);
  const data=jest.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,cG5n');
  const frame={sourceId:'cam',sessionId:'session',sourceTimeNs:String(BigInt(Date.now())*BigInt(1000000)),snapshot:{siteId:'site',analyticsScope:{kind:'normal',epoch:'epoch',suppressed:false}}} as CityVideoFrame;
  const remove=registerScenarioCamera('cam',()=>({image:video,frame}));
  expect(captureSceneFrame(identity)).toEqual({...identity,sourceTimeNs:frame.sourceTimeNs,imageBase64:'cG5n'});
  expect(drawImage).toHaveBeenCalledWith(video,0,0,1280,480);
  expect(captureScenarioFrame({...identity,runId:'run',scenarioId:'crossing-occupancy'})).toBeNull();
  expect(captureSceneFrame({...identity,epoch:'old'})).toBeNull();
  frame.sourceTimeNs='1';expect(captureSceneFrame(identity)).toBeNull();
  remove();context.mockRestore();data.mockRestore();expect(captureSceneFrame(identity)).toBeNull();
});
test('captures the frozen raw callback pixels for a scenario without adding overlays',()=>{
  const image = document.createElement('canvas'); image.width = 1280; image.height = 480;
  const drawImage=jest.fn(); const context=jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage} as any);
  const data=jest.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,cG5n');
  const frame={sourceId:'cam',sessionId:'session',sourceTimeNs:String(BigInt(Date.now())*BigInt(1000000)),snapshot:{siteId:'site',analyticsScope:{kind:'scenario',epoch:'epoch',runId:'run',scenarioId:'queue-blockage',suppressed:false}}} as CityVideoFrame;
  const remove=registerScenarioCamera('cam',()=>({image,frame}));
  expect(captureScenarioFrame({...identity,runId:'run',scenarioId:'queue-blockage'})).toEqual({...identity,runId:'run',scenarioId:'queue-blockage',sourceTimeNs:frame.sourceTimeNs,imageBase64:'cG5n'});
  expect(drawImage).toHaveBeenCalledWith(image,0,0,1280,480);
  remove(); context.mockRestore(); data.mockRestore();
});
