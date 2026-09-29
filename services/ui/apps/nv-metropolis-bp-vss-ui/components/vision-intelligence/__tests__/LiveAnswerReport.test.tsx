// SPDX-License-Identifier: MIT
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { LiveAnswerReport, liveAnswerReportRequest } from "../LiveAnswerReport";
import type { VisionAnalystResponse } from "../analyst";
const source = {kind:"live" as const, name:"Simulation replay", sensorId:"sensor-one", streamId:"stream-one"};
const result: VisionAnalystResponse = {
  answer:"A package moves along the conveyor.", evidenceTools:["video_understanding_iso"],
  generatedAt:"2026-09-28T23:00:35Z", grounded:true, query:"What moves?", scope:"selected-source", sourceNames:[source.name],
  observedWindow:{startTime:"2026-09-28T23:00:00Z",endTime:"2026-09-28T23:00:25Z"},
};
afterEach(()=>jest.restoreAllMocks());
it("preserves exact source, interval, answer and notes without marking the result reviewed",()=>{
  const request=liveAnswerReportRequest(result,source,"Camera briefing","Simulation; movement checked in the cited clip.");
  expect(request).toMatchObject({title:"Camera briefing",notes:"Simulation; movement checked in the cited clip.",disposition:"under_review",
    analysis:{summary:result.answer,question:result.query,observations:[{text:result.answer,evidence_ids:["E1"]}]},
    evidence:[{sensor_id:"sensor-one",start_time:result.observedWindow!.startTime,end_time:result.observedWindow!.endTime}]});
});
it("rejects missing or invalid inspected intervals",()=>{
  expect(()=>liveAnswerReportRequest({...result,observedWindow:undefined},source,"title","")).toThrow(/interval/);
  expect(()=>liveAnswerReportRequest({...result,observedWindow:{startTime:"bad",endTime:"bad"}},source,"title","")).toThrow(/interval/);
});
it("saves through the report API and reports the actual media retention outcome",async()=>{
  global.fetch=jest.fn(async()=>({ok:true,json:async()=>({report_url:"/report?id=saved",evidence:[{media_status:"source_retention"}]})})) as jest.Mock;
  render(<LiveAnswerReport result={result} source={source}/>);
  fireEvent.click(screen.getByRole('button',{name:'Save report',exact:true}));
  fireEvent.change(screen.getByLabelText('Live report notes'),{target:{value:'Needs review'}});
  fireEvent.click(screen.getByRole('button',{name:'Save report with evidence'}));
  await screen.findByText(/Video still depends on source retention/);
  expect(screen.getByRole('link',{name:'Open report'})).toHaveAttribute('href','/report?id=saved');
  expect(JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body).notes).toBe('Needs review');
});
it("keeps notes for retry when saving fails",async()=>{
  global.fetch=jest.fn(async()=>({ok:false,json:async()=>({error:'Storage unavailable'})})) as jest.Mock;
  render(<LiveAnswerReport result={result} source={source}/>);
  fireEvent.click(screen.getByRole('button',{name:'Save report',exact:true}));
  fireEvent.change(screen.getByLabelText('Live report notes'),{target:{value:'Keep this note'}});
  fireEvent.click(screen.getByRole('button',{name:'Save report with evidence'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Storage unavailable');
  expect(screen.getByLabelText('Live report notes')).toHaveValue('Keep this note');
});
