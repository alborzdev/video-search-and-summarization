/** @jest-environment node */
// SPDX-License-Identifier: MIT
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { acquireObservationLane, readObservationLane, writeObservationLane, sharedObservation } from '../../../server/vision/scenarioObservationLane';
let directory:string;const original=process.env.VISION_HISTORY_DIR;
beforeEach(async()=>{directory=await mkdtemp(path.join(os.tmpdir(),'vss-observation-test-'));process.env.VISION_HISTORY_DIR=directory;});
afterEach(async()=>{if(original===undefined)delete process.env.VISION_HISTORY_DIR;else process.env.VISION_HISTORY_DIR=original;await rm(directory,{recursive:true,force:true});});
test('OS lock excludes a second process and releases cleanly',async()=>{
 const release=await acquireObservationLane();expect(release).not.toBeNull();
 try { expect(await acquireObservationLane()).toBeNull();await writeObservationLane({nextAt:123});expect(await readObservationLane()).toEqual({nextAt:123}); }
 finally { await release!(); }
 const second=await acquireObservationLane();expect(second).not.toBeNull();await second!();
});
test('only shares fresh observations from the same run and camera session',()=>{
 const identity={epoch:'epoch',runId:'run',scenarioId:'crossing-occupancy',sourceId:'cam',sessionId:'session'};
 const observation={...identity,sourceTimeNs:String(BigInt(Date.now())*BigInt(1000000)),observedAt:new Date().toISOString(),completedAt:new Date().toISOString(),text:'People occupy the crossing.',model:'cosmos',inferenceMs:1200};
 const frame={...identity,siteId:'site',imageBase64:'png',sourceTimeNs:observation.sourceTimeNs};
 expect(sharedObservation({nextAt:0,observation},frame)).toEqual(observation);
 expect(sharedObservation({nextAt:0,observation},{...frame,epoch:'next'})).toBeNull();
 expect(sharedObservation({nextAt:0,observation:{...observation,observedAt:new Date(Date.now()-9000).toISOString()}},frame)).toBeNull();
});
