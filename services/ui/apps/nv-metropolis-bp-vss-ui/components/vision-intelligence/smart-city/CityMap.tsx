// SPDX-License-Identifier: MIT
import React, { memo, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { IconFocus2, IconInfoCircle, IconLayersIntersect, IconMapPin, IconMinus, IconPlus, IconVideo } from '@tabler/icons-react';
import type { CityRule, CitySite, CitySnapshot, Point } from './types';
import { objectName, ruleGroundPoints } from './geometry';
import styles from './SmartCity.module.css';
import { cameraColor, groupRuleGeometry, sourceName } from './presentation';
import { areaLabel } from './overviewObservation';
import { deriveMapObjects, hasNativeMapPosition, usesNativeMapPositions, type CityMapObject } from './mapObjects';
import { cameraViewCue, mapBackdrop } from './mapPresentation';

export interface QueueMapOverlay {
  name: string; sourceId: string; stopLineM: Point[]; upstreamPointM: Point;
  tailPositionM?: Point | null; status: string; observedExtentM?: number | null;
}

export const CityMap = memo(function CityMap({ site, snapshot, rules, selectedTrack, onSelect, focusedRuleId, onGroundPoint, groundDraft, groundPrompt, onCancelGround, queueOverlay, mapObjects, children, contextClassName, analysisEnabled = true, showAllRules = false, inspectable = true, onFocusRule, onPreviewRule, onClearFocus }: {
  site: CitySite; snapshot: CitySnapshot | null; rules: CityRule[];
  selectedTrack: string | null; onSelect: (id: string) => void;
  focusedRuleId?: string | null; onGroundPoint?: (point: Point) => void; groundDraft?: Point[];
  groundPrompt?: string; onCancelGround?: () => void; queueOverlay?: QueueMapOverlay | null;
  mapObjects?: CityMapObject[]; children?: React.ReactNode; contextClassName?: string; analysisEnabled?: boolean; showAllRules?: boolean;
  inspectable?: boolean; onFocusRule?: (id: string) => void; onPreviewRule?: (id: string | null) => void; onClearFocus?: () => void;
}) {
  type Target = { kind: 'camera' | 'area'; id: string };
  const mapRoot = useRef<HTMLElement>(null);
  const [hovered, setHovered] = useState<Target | null>(null);
  const [pinned, setPinned] = useState<Target | null>(null);
  const [areasVisible, setAreasVisible] = useState(true);
  const [guideOpen, setGuideOpen] = useState(false);
  const clearInspection = useCallback(() => { setPinned(null); setHovered(null); onClearFocus?.(); }, [onClearFocus]);
  useEffect(() => {
    if (!pinned || !inspectable) return;
    const dismiss = (event: PointerEvent) => { if (event.target instanceof Node && !mapRoot.current?.contains(event.target)) clearInspection(); };
    document.addEventListener('pointerdown', dismiss, true);
    return () => document.removeEventListener('pointerdown', dismiss, true);
  }, [pinned, inspectable, clearInspection]);
  useEffect(() => { if (!inspectable) { setPinned(null); setHovered(null); } }, [inspectable]);
  const inspected = inspectable ? hovered ?? pinned : null;
  const [zoom, setZoom] = useState(1); const [pan, setPan] = useState<Point>([0, 0]);
  const dragging = useRef<{ pointerId: number; point: Point; pan: Point } | null>(null);
  const [minX, minY, maxX, maxY] = site.map.bounds;
  const calibrated = site.sources.some(source => source.imageToGroundHomography);
  const gridId = useId();
  useEffect(() => { setZoom(1); setPan([0, 0]); dragging.current = null; setHovered(null); setPinned(null); }, [site.id, minX, minY, maxX, maxY]);
  const width = Math.max(1, maxX - minX); const height = Math.max(1, maxY - minY);
  const scale = Math.max(width, height) / 130;
  const cameras = useMemo(() => site.sources.map((source, index) => ({ source, index, cue: cameraViewCue(source, scale * 22) })).filter(camera => camera.cue !== null), [site.sources, scale]);
  const backdrop = mapBackdrop(site); const imageUrl = backdrop?.imageUrl ?? null;
  const imageBounds = backdrop?.bounds ?? site.map.bounds; const minimumZoom = backdrop?.minimumZoom ?? .5;
  const view = `${minX - width * .03} ${minY - height * .03} ${width * 1.06} ${height * 1.06}`;
  const geometry = useMemo(() => groupRuleGeometry(rules.filter(rule => rule.enabled)).map(group => { const rule = group.rules[0]; return { group, points: ruleGroundPoints(rule.geometry.points, rule.geometry.space, site.sources.find(source => source.id === rule.sourceId)) }; }).filter(item => item.points.length > 1), [rules, site.sources]);
  const objects = useMemo(() => mapObjects ?? deriveMapObjects(site, snapshot), [mapObjects, site, snapshot]);
  const experimental = snapshot?.association?.mapFusion?.enabled === true && snapshot.association.mapFusion.mode === 'mv3dt-demo';
  const sharedCount = objects.filter(object => object.shared).length;
  const disputedPositions = objects.filter(object => (object.nativePositionSpreadM ?? 0) > 1).length;
  const withheldPositions = usesNativeMapPositions(snapshot) ? snapshot!.tracks.filter(track => !track.stale &&
    track.observedThisFrame !== false && track.positionM && !hasNativeMapPosition(track)).length : 0;
  const zoneLayers = geometry.filter(layer => showAllRules || inspectable && areasVisible || layer.group.rules.some(rule => rule.id === focusedRuleId)).map(layer => ({ ...layer, active: Boolean(snapshot?.zones.some(zone => layer.group.rules.some(rule => rule.id === zone.id) && zone.active)) }))
    .sort((a, b) => Number(a.active) - Number(b.active));
  const inspectedArea = inspected?.kind === 'area' ? geometry.find(layer => layer.group.key === inspected.id) : null;
  const previewedRuleId = inspectedArea?.group.rules[0].id ?? null;
  useEffect(() => { onPreviewRule?.(previewedRuleId); }, [onPreviewRule, previewedRuleId]);
  useEffect(() => () => onPreviewRule?.(null), [onPreviewRule]);
  const inspect = (target: Target) => { setPinned(target); if (target.kind === 'area') { const rule = geometry.find(layer => layer.group.key === target.id)?.group.rules[0]; if (rule) onFocusRule?.(rule.id); } };
  const path = (values: Point[]) => values.map(([x, y]) => `${x},${maxY + minY - y}`).join(' ');
  return <section ref={mapRoot} className={styles.map} aria-label="Calibrated live top-down map" onMouseLeave={() => setHovered(null)} onKeyDown={event => { if (event.key === 'Escape') { clearInspection(); setGuideOpen(false); } }}>
    <div className={styles.mapHeading}><div className={styles.mapHeadingText}><strong>{groundPrompt ?? 'Intersection map'}</strong><span title={snapshot?.mode === 'live' && snapshot.videoFrameMatched ? 'Positions come from the matching analyzed camera frames. Absolute camera capture time is not independently verified.' : undefined}>{onGroundPoint ? 'Three map points · site metres' : queueOverlay ? `${queueOverlay.name} · estimated queue anchors` : site.mode === 'live' && !analysisEnabled ? 'Detections off' : calibrated ? snapshot?.mode === 'live' ? snapshot.videoFrameMatched ? 'Estimated ground positions' : snapshot.videoClockAligned ? 'Camera-aligned ground positions' : 'Source positions · video clock unverified' : 'Calibrated ground positions' : 'Calibration required'}</span></div>
      {inspectable && <div className={styles.mapToolbar}>
        <button type="button" aria-pressed={areasVisible} aria-label="Show monitoring areas" onClick={() => { setAreasVisible(value => !value); setHovered(null); }}><IconLayersIntersect size={16} />Areas</button>
        <button type="button" aria-expanded={guideOpen} aria-controls={`${gridId}-guide`} onClick={() => setGuideOpen(value => !value)}><IconInfoCircle size={16} />Map key</button>
      </div>}
    </div>
    <div className={styles.mapViewport}>
    <svg viewBox={view} preserveAspectRatio="xMidYMid slice" tabIndex={-1} className={`${styles.mapCanvas} ${!calibrated ? styles.mapUncalibrated : ''}`} style={onGroundPoint ? { cursor: 'crosshair' } : undefined} aria-label="Top-down camera observations in metres" onClick={event => { if (inspectable && !onGroundPoint && !(event.target as Element).closest('[data-map-interactive]')) clearInspection(); }} onClickCapture={event => {
      if (!onGroundPoint || !calibrated) return;
      event.preventDefault(); event.stopPropagation();
      const matrix = event.currentTarget.getScreenCTM(); if (!matrix) return;
      const point = event.currentTarget.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
      const local = point.matrixTransform(matrix.inverse());
      const cx = (minX + maxX) / 2; const cy = (minY + maxY) / 2;
      const x = (local.x - pan[0] - cx) / zoom + cx;
      const y = minY + maxY - ((local.y - pan[1] - cy) / zoom + cy);
      if (x >= minX && x <= maxX && y >= minY && y <= maxY) onGroundPoint([Number(x.toFixed(3)), Number(y.toFixed(3))]);
    }} onPointerDown={event => {
      if (onGroundPoint || !calibrated || event.button !== 0 || event.isPrimary === false || dragging.current || (event.target as Element).closest('[data-map-interactive]')) return;
      event.preventDefault();
      if (inspectable) { clearInspection(); event.currentTarget.focus(); }
      event.currentTarget.setPointerCapture(event.pointerId); dragging.current = { pointerId: event.pointerId, point: [event.clientX, event.clientY], pan };
    }} onPointerMove={event => {
      const drag = dragging.current; if (!drag || drag.pointerId !== event.pointerId) return;
      const rect = event.currentTarget.getBoundingClientRect(); if (!rect.width || !rect.height) return; const factor = Math.min(width * 1.06 / rect.width, height * 1.06 / rect.height);
      setPan([drag.pan[0] + (event.clientX - drag.point[0]) * factor, drag.pan[1] + (event.clientY - drag.point[1]) * factor]);
    }} onPointerUp={event => { if (dragging.current?.pointerId === event.pointerId) { dragging.current = null; if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); } }} onPointerCancel={event => { if (dragging.current?.pointerId === event.pointerId) dragging.current = null; }} onLostPointerCapture={event => { if (event.pointerId === undefined || dragging.current?.pointerId === event.pointerId) dragging.current = null; }}>
      <defs><pattern id={gridId} width={5} height={5} patternUnits="userSpaceOnUse"><path d="M 5 0 L 0 0 0 5" fill="none" stroke="#29403c" strokeWidth=".08" /></pattern>{cameras.map(({source, index, cue}) => <radialGradient key={source.id} id={`${gridId}-cone-${index}`} gradientUnits="userSpaceOnUse" cx={cue!.origin[0]} cy={maxY + minY - cue!.origin[1]} r={scale * 22}><stop offset="0" stopColor={cameraColor(index)} stopOpacity=".5" /><stop offset=".7" stopColor={cameraColor(index)} stopOpacity=".2" /><stop offset="1" stopColor={cameraColor(index)} stopOpacity=".025" /></radialGradient>)}</defs>
      <rect x={minX - width} y={minY - height} width={width * 3} height={height * 3} fill="#171a1c" />
      <g transform={`translate(${pan[0]} ${pan[1]}) translate(${(minX + maxX) / 2} ${(minY + maxY) / 2}) scale(${zoom}) translate(${-(minX + maxX) / 2} ${-(minY + maxY) / 2})`}>
        <rect x={minX} y={minY} width={width} height={height} fill={`url(#${gridId})`} />
        {imageUrl && <image className={styles.mapBackdrop} aria-label="Static intersection map" href={imageUrl} x={imageBounds[0]} y={minY + maxY - imageBounds[3]} width={imageBounds[2] - imageBounds[0]} height={imageBounds[3] - imageBounds[1]} preserveAspectRatio="none" />}
        {!imageUrl && site.map.buildings.map(building => <polygon key={building.id} points={path(building.points)} fill="#26332e" stroke="#42504a" strokeWidth={scale * .14} />)}
        {!imageUrl && site.map.roads.map(road => <g key={road.id}><polyline points={path(road.points)} fill="none" stroke="#33413e" strokeWidth={(road.width ?? 7) + scale * .5} strokeLinejoin="round" /><polyline points={path(road.points)} fill="none" stroke="#24322f" strokeWidth={road.width ?? 7} strokeLinejoin="round" /><polyline points={path(road.points)} fill="none" stroke="#8d9e91" strokeOpacity=".6" strokeWidth={scale * .12} strokeDasharray={`${scale * 2} ${scale * 2}`} /></g>)}
        {cameras.map(({ source, index, cue }) => {
          const { cone } = cue!; const color = cameraColor(index);
          const highlighted = inspected?.kind === 'camera' && inspected.id === source.id;
          return <g key={source.id} className={styles.cameraFootprint} data-inspected={highlighted} style={{ '--camera-color': color } as React.CSSProperties} aria-label={`Camera ${String(index + 1).padStart(2, '0')} · ${sourceName(source)} · calibrated view direction`}>
            <polygon className={styles.viewCone} points={path(cone)} fill={`url(#${gridId}-cone-${index})`} stroke={color} strokeWidth={scale * .15} />
          </g>;
        })}
        {zoneLayers.map(({ group, points, active }) => {
          const focused = group.rules.some(rule => rule.id === focusedRuleId);
          const highlighted = inspected ? inspected.kind === 'area' && inspected.id === group.key : focused;
          const target: Target = { kind: 'area', id: group.key };
          const interactive = inspectable ? { 'data-map-interactive': true, role: 'button', tabIndex: 0,
            'aria-label': `${areaLabel(group.rules[0].name)} · ${group.caption} · monitoring area`, 'aria-pressed': pinned?.kind === 'area' && pinned.id === group.key,
            onMouseEnter: () => setHovered(target), onMouseLeave: () => setHovered(null), onFocus: () => setHovered(target), onBlur: () => setHovered(null),
            onClick: () => inspect(target), onKeyDown: (event: React.KeyboardEvent<SVGGElement>) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); inspect(target); } if (event.key === 'Escape') clearInspection(); },
          } : {};
          return <g key={group.key} className={`${active ? styles.activeZone : styles.zone} ${styles.mapZone}`} data-focused={highlighted} {...interactive}>
            {points.length === 2 ? <><polyline className={styles.areaShape} vectorEffect="non-scaling-stroke" points={path(points)} fill="none" strokeWidth={scale * .2} /><polyline className={styles.areaHitTarget} points={path(points)} fill="none" strokeWidth="16" vectorEffect="non-scaling-stroke" /></> : <polygon className={styles.areaShape} vectorEffect="non-scaling-stroke" points={path(points)} strokeWidth={scale * .16} />}
            {highlighted && <g className={styles.mapAreaLabel} pointerEvents="none" transform={`translate(${points[0][0]} ${maxY + minY - points[0][1]})`}><rect x={scale} y={-scale * 3.1} width={Math.max(12, areaLabel(group.rules[0].name).length * .9) * scale} height={scale * 2.6} rx={scale * .45} /><text x={scale * 1.7} y={-scale * 1.25} fontSize={scale * 1.6}>{areaLabel(group.rules[0].name)}</text></g>}
          </g>;
        })}
        {cameras.map(({ source, index, cue }) => {
          const [x, y] = cue!.origin; const cy = maxY + minY - y; const color = cameraColor(index); const target: Target = {kind: 'camera', id: source.id};
          const selected = inspected?.kind === 'camera' && inspected.id === source.id;
          return <g key={source.id} className={styles.cameraPin} data-inspected={selected} data-map-interactive={inspectable || undefined} style={{ '--camera-color': color } as React.CSSProperties}
            role={inspectable ? 'button' : undefined} tabIndex={inspectable ? 0 : undefined} aria-label={`Inspect camera ${String(index + 1).padStart(2, '0')} · ${sourceName(source)}`} aria-pressed={inspectable ? pinned?.kind === 'camera' && pinned.id === source.id : undefined}
            onMouseEnter={() => { if (inspectable) setHovered(target); }} onMouseLeave={() => setHovered(null)} onFocus={() => { if (inspectable) setHovered(target); }} onBlur={() => setHovered(null)} onClick={() => { if (inspectable) inspect(target); }}
            onKeyDown={event => { if (!inspectable) return; if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); inspect(target); } if (event.key === 'Escape') clearInspection(); }}>
            <circle className={styles.cameraHalo} cx={x} cy={cy} r={scale * 3.1} fill={color} fillOpacity=".12" />
            <circle cx={x} cy={cy} r={scale * 2} fill="#122429" stroke={color} strokeWidth={scale * .3} />
            <IconVideo x={x - scale * 1.15} y={cy - scale * 1.15} width={scale * 2.3} height={scale * 2.3} color={color} strokeWidth={1.8} />
            <rect x={x - scale * 1.5} y={cy + scale * 2.4} width={scale * 3} height={scale * 2.2} rx={scale * .45} fill="#122025" stroke={color} strokeWidth={scale * .12} />
            <text x={x} y={cy + scale * 4.05} textAnchor="middle" fill="#f2f8fa" fontSize={scale * 1.75}>{String(index + 1).padStart(2, '0')}</text>
            <circle cx={x} cy={cy} r={scale * 2.5} fill="transparent" stroke="transparent" strokeWidth="12" vectorEffect="non-scaling-stroke" />
          </g>;
        })}
        {queueOverlay?.stopLineM?.length === 2 && <g aria-label={`${queueOverlay.name} queue geometry`} pointerEvents="none">
          <polyline points={path(queueOverlay.stopLineM)} stroke="#68e3df" strokeWidth={scale * .5} fill="none" />
          <polyline points={path([[ (queueOverlay.stopLineM[0][0] + queueOverlay.stopLineM[1][0]) / 2, (queueOverlay.stopLineM[0][1] + queueOverlay.stopLineM[1][1]) / 2 ], queueOverlay.upstreamPointM])} stroke="#68e3df" strokeWidth={scale * .25} strokeDasharray={`${scale} ${scale}`} fill="none" opacity=".7" />
          {queueOverlay.tailPositionM && !['unknown', 'disabled'].includes(queueOverlay.status) && <circle cx={queueOverlay.tailPositionM[0]} cy={maxY + minY - queueOverlay.tailPositionM[1]} r={scale * 1.7} fill="none" stroke={queueOverlay.status === 'spillback' ? '#fbad68' : '#68e3df'} strokeWidth={scale * .45} />}
        </g>}
        {!!groundDraft?.length && <g aria-label="Queue axis drawing" pointerEvents="none"><polyline points={path(groundDraft)} stroke="#68e3df" strokeWidth={scale * .5} fill="none" />{groundDraft.map(([x, y], index) => <g key={index}><circle cx={x} cy={maxY + minY - y} r={scale * 1.2} fill="#68e3df" /><text x={x + scale * 1.6} y={maxY + minY - y} fontSize={scale * 1.8} fill="white">{index + 1}</text></g>)}</g>}
        {objects.map(object => {
          const track = object.track;
          const [x, y] = track.positionM!; const selected = selectedTrack !== null && object.memberTrackIds.includes(selectedTrack);
          const vehicle = ['car', 'bus', 'truck', 'motorcycle', 'two-wheeler', 'vehicle'].includes(track.class.toLowerCase());
          const source = site.sources.find(source => source.id === track.sourceId);
          const cameras = object.sourceIds.map(id => site.sources.find(source => source.id === id)).map(source => source ? sourceName(source) : 'Camera').join(' + ');
          const label = object.shared ? `${objectName(track.class)} · ${object.memberTrackIds.length} camera views` : objectName(track.class);
          return <g key={object.id} data-map-interactive data-track={object.id} data-member-track-ids={JSON.stringify(object.memberTrackIds)} data-shared={object.shared || undefined} role="button" tabIndex={0} aria-label={object.shared ? `${label} · ${cameras} on map` : `${label} · ${source ? sourceName(source) : track.sourceId} on map`} aria-pressed={selected}
            className={`${styles.mapTrack} ${selected ? styles.selectedTrack : ''}`}
            onClick={() => { setPinned(null); setHovered(null); onSelect(track.id); }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setPinned(null); setHovered(null); onSelect(track.id); } }}>
            {(object.nativePositionSpreadM ?? 0) > 1 && <g pointerEvents="none"><title>{`Shared MV3DT ID · camera positions differ by ${object.nativePositionSpreadM!.toFixed(1)} m`}</title><circle data-position-disagreement cx={x} cy={maxY + minY - y} r={scale * 1.65} fill="none" stroke="#e3b563" strokeWidth={scale * .18} strokeDasharray={`${scale * .45} ${scale * .3}`} /></g>}
            {(selected || zoom > 1.5) && track.trail.length > 1 && <polyline points={path(track.trail.map(item => item.positionM))} fill="none" strokeWidth={scale * .25} opacity=".4" pointerEvents="none" />}
            {selected && <circle cx={x} cy={maxY + minY - y} r={scale * 2.2} className={styles.mapSelection} pointerEvents="none" />}
            {object.shared && <g pointerEvents="none" aria-hidden="true"><title>One {object.track.class} · {object.sourceIds.length} camera views</title>{object.sourceIds.map((sourceId, index) => {
              const radius = scale * 1.15; const centerY = maxY + minY - y;
              const start = -Math.PI / 2 + index * Math.PI * 2 / object.sourceIds.length + .12;
              const end = -Math.PI / 2 + (index + 1) * Math.PI * 2 / object.sourceIds.length - .12;
              return <path key={sourceId} d={`M ${x + Math.cos(start) * radius} ${centerY + Math.sin(start) * radius} A ${radius} ${radius} 0 0 1 ${x + Math.cos(end) * radius} ${centerY + Math.sin(end) * radius}`} fill="none" stroke={cameraColor(site.sources.findIndex(source => source.id === sourceId))} strokeWidth={scale * .32} strokeLinecap="round" />;
            })}</g>}
            {vehicle ? <rect className={styles.mapMarker} x={x - scale * .85} y={maxY + minY - y - scale * 1.35} width={scale * 1.7} height={scale * 2.7} rx={scale * .3} strokeWidth={scale * .2} pointerEvents="none" /> : <circle className={styles.mapMarker} cx={x} cy={maxY + minY - y} r={scale * .85} strokeWidth={scale * .2} pointerEvents="none" />}
            <circle className={styles.mapHitTarget} cx={x} cy={maxY + minY - y} r={scale * .65} strokeWidth="24" vectorEffect="non-scaling-stroke" aria-hidden="true" />
            {(selected || zoom > 1.5) && <text x={x + scale * 1.2} y={maxY + minY - y - scale * .8} fontSize={scale * 1.8} pointerEvents="none">{label}</text>}
          </g>;
        })}
      </g>
    </svg>
    {!calibrated && <div className={styles.mapEmpty}><IconMapPin size={52} stroke={1} aria-hidden="true" /><strong>Connect the cameras to your site</strong><span>Add camera calibration to place tracked objects on the map.</span></div>}
    {calibrated && <div className={styles.north}><span>N</span><svg viewBox="0 0 18 20"><path d="M9 1 16 18 9 14 2 18Z" fill="currentColor" /></svg></div>}

    {calibrated && <div className={styles.mapControls}>{onGroundPoint && <button type="button" aria-label="Cancel queue axis drawing" title="Cancel drawing" onClick={onCancelGround}>×</button>}<button type="button" aria-label="Reset map view" onClick={() => { dragging.current = null; setZoom(1); setPan([0, 0]); }}><IconFocus2 size={20} /></button><button type="button" aria-label="Zoom map in" disabled={zoom >= 6} onClick={() => setZoom(value => Math.min(6, value * 1.25))}><IconPlus size={20} /></button><button type="button" aria-label="Zoom map out" disabled={zoom <= minimumZoom} onClick={() => setZoom(value => Math.max(minimumZoom, value / 1.25))}><IconMinus size={20} /></button></div>}
    </div>
    {usesNativeMapPositions(snapshot) && <div className={styles.mapPositionNote} role="status" title="Dashed amber rings mark shared SDK identities whose camera positions differ by more than one metre. Camera detections remain visible.">{disputedPositions > 0 ? `${disputedPositions} shared ${disputedPositions === 1 ? 'ID has' : 'IDs have'} uncertain position${withheldPositions > 0 ? ` · ${withheldPositions} invalid positions hidden` : ''}` : withheldPositions > 0 ? `${withheldPositions} uncertain map ${withheldPositions === 1 ? 'position' : 'positions'} hidden · camera detections remain visible` : 'Uncertain map positions are hidden · camera detections remain visible'}</div>}
    {inspectable && <div id={`${gridId}-guide`} hidden={!guideOpen} className={styles.mapLegend}><div className={styles.mapSymbolKey}><span><i />People</span><span><i />Vehicles</span></div>{calibrated && <><strong title="Map markers are observations, not a unique site count.">{objects.length} {experimental ? `map object${objects.length === 1 ? '' : 's'}` : `observation${objects.length === 1 ? '' : 's'}`}</strong><div className={styles.cameraKeys}>{site.sources.map((source, index) => <span key={source.id}><i style={{ background: cameraColor(index) }} />{sourceName(source)}</span>)}</div></>}<span className={styles.mapIdentityNote}>{experimental ? `Display association · ${sharedCount} linked ${sharedCount === 1 ? 'object' : 'objects'} · unmatched camera views can show an object twice` : 'Camera-owned observations · overlap can show an object twice'}</span></div>}
    {React.Children.toArray(children).length > 0 && <div className={`${styles.mapContext} ${contextClassName ?? ''}`}>{children}</div>}
  </section>;
});
