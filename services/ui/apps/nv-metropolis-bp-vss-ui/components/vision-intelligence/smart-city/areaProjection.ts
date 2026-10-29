// SPDX-License-Identifier: MIT
import type {CityRule, CitySource, Point} from './types';
import {projectPoint, ruleGroundPoints} from './geometry';
export interface GroundAreaHighlight {id:string; name:string; sourceId:string; points:Point[];}

export function groundAreaHighlight(rule:CityRule | undefined, sources:CitySource[]):GroundAreaHighlight | null {
  if (!rule?.enabled) return null;
  const owner = sources.find(source=>source.id===rule.sourceId);
  if (!owner || rule.calibrationRevision && rule.calibrationRevision!==owner.calibrationRevision) return null;
  const points = ruleGroundPoints(rule.geometry.points,rule.geometry.space,owner);
  if(points.length<2 || points.some(point=>!point.every(Number.isFinite))) return null;
  return {id:rule.id,name:rule.name,sourceId:rule.sourceId,points};
}
/** Clip before projection so an area outside this camera's ground view never wraps across the horizon. */
export function clipGroundArea(points:Point[], boundary:Point[]):Point[] {
  if(points.length<2 || boundary.length<3 || [...points,...boundary].some(point=>point.length!==2||!point.every(Number.isFinite))) return [];
  const signedArea=boundary.reduce((sum,[x,y],index)=>{const next=boundary[(index+1)%boundary.length];return sum+x*next[1]-next[0]*y;},0);
  if(Math.abs(signedArea)<1e-9) return [];
  const orientation=Math.sign(signedArea); let result=points;
  for(let index=0;index<boundary.length;index++){
    const a=boundary[index],b=boundary[(index+1)%boundary.length];
    const distance=([x,y]:Point)=>orientation*((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]));
    const intersection=(p:Point,q:Point,dp:number,dq:number):Point=>{const t=dp/(dp-dq);return [p[0]+(q[0]-p[0])*t,p[1]+(q[1]-p[1])*t];};
    if(points.length===2){
      if(result.length<2)return [];
      const [p,q]=result,dp=distance(p),dq=distance(q); if(dp<0&&dq<0)return [];
      if(dp<0)result=[intersection(p,q,dp,dq),q]; else if(dq<0)result=[p,intersection(p,q,dp,dq)];
    } else {
      const output:Point[]=[]; if(!result.length)return [];
      for(let i=0;i<result.length;i++){
        const p=result[(i+result.length-1)%result.length],q=result[i],dp=distance(p),dq=distance(q);
        if(dq>=0){if(dp<0)output.push(intersection(p,q,dp,dq));output.push(q);}else if(dp>=0)output.push(intersection(p,q,dp,dq));
      }
      result=output;
    }
  }
  return result.length>=(points.length===2?2:3)?result:[];
}
/** Presentation only: does not create a rule or borrow another camera's counts. */
export function areaInCamera(area:GroundAreaHighlight | null | undefined, source:CitySource):Point[] {
  if(!area || !source.calibrationRevision || !source.groundCoverageM || source.width<=0 || source.height<=0) return [];
  const matrix=source.imageToGroundHomography;
  if(!matrix || matrix.length!==3 || matrix.some(row=>row.length!==3) || !matrix.flat().every(Number.isFinite))return [];
  const scale=Math.max(...matrix.flat().map(Math.abs));if(!scale)return [];
  const [[a,b,c],[d,e,f],[g,h,i]]=matrix.map(row=>row.map(value=>value/scale));
  if(Math.abs(a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g))<Number.EPSILON*1e-6)return [];
  const inverse=[[e*i-f*h,c*h-b*i,b*f-c*e],[f*g-d*i,a*i-c*g,c*d-a*f],[d*h-e*g,b*g-a*h,a*e-b*d]];
  const ground=clipGroundArea(area.points,source.groundCoverageM); if(!ground.length)return [];
  const projected=ground.map(point=>projectPoint(point,inverse));if(projected.some(point=>!point))return [];
  const normalized=(projected as Point[]).map(([x,y]):Point=>[x/source.width,y/source.height]);
  return clipGroundArea(normalized,[[0,0],[1,0],[1,1],[0,1]]);
}
