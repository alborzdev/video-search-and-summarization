// SPDX-License-Identifier: MIT
import React from "react";
import s from "./CityCameraStory.module.css";

// Image-space coordinates follow the painted crosswalk from curb to curb.
export const crossingZone = "M580 546 976 650 954 691 552 581Z";

export type Track = { id: string; x: number; y: number; width: number; height: number; color: string };
export function TrackBox({ track, delay = 0, muted = false, labelScale = 1, labelOffsetX = 0 }: { track: Track; delay?: number; muted?: boolean; labelScale?: number; labelOffsetX?: number }) {
  const { x, y, width, height, color, id } = track;
  return <g className={s.track} style={{color, animationDelay: `${delay}s`, opacity: muted ? .55 : 1}}>
    <rect x={x-5} y={y-5} width={width+10} height={height+10} rx="3" fill="none" stroke="currentColor" strokeWidth="1.4" vectorEffect="non-scaling-stroke"/>
    <g transform={`translate(${x-5+labelOffsetX} ${y-7}) scale(${labelScale})`}><rect y="-27" width="76" height="27" rx="4" fill="currentColor"/><text x="8" y="-8" fill="#14261d" fontSize="17" fontWeight="600">{id}</text></g>
  </g>;
}
