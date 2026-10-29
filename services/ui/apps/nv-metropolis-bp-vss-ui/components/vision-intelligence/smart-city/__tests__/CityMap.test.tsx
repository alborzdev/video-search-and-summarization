// SPDX-License-Identifier: MIT
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { CityMap } from '../CityMap';
import type { CitySite, CitySnapshot } from '../types';
const source = { id: 'camera', name: 'Camera', width: 1000, height: 1000, imageToGroundHomography: [[1, 0, 0], [0, 1, 0], [0, 0, 1]] as [[number, number, number], [number, number, number], [number, number, number]] };
const site: CitySite = { id: 'city', name: 'City', mode: 'live', revision: 1, sources: [source], map: { bounds: [0, 0, 100, 100], roads: [], buildings: [] } };
const snapshot: CitySnapshot = { siteId: 'city', mode: 'live', timestamp: '2026-10-22T00:00:00Z', sequence: 1, sources: [source], zones: [], rules: [], events: [], metrics: [], tracks: [
  { id: 'person', sourceId: source.id, sessionId: 'epoch', localTrackId: '7', class: 'person', bboxPx: [10, 10, 20, 40], positionM: [20, 30], confidence: .9, stale: false, trail: [] },
  { id: 'car', sourceId: source.id, sessionId: 'epoch', localTrackId: '8', class: 'car', bboxPx: [40, 40, 60, 30], positionM: [30, 40], confidence: .9, stale: false, trail: [] },
] };
const props = { site, snapshot, rules: [], selectedTrack: null, onSelect: jest.fn() };
describe('city map interactions', () => {
  it('uses real exported camera positions for direction cues and omits uncalibrated poses', () => {
    const pose = {...source,calibrationRevision:'cal-1',cameraPositionWorldM:[12,0,8] as [number,number,number],groundCoverageM:[[10,10],[30,10],[30,30]] as [number,number][]};
    const {rerender} = render(<CityMap {...props} site={{...site,sources:[pose]}} />);
    const camera = screen.getByLabelText('Camera 01 · Camera · calibrated view direction');
    expect(camera.querySelector('polygon')?.getAttribute('points')).toMatch(/^12,100 /);
    expect(camera.querySelector('line')).toBeNull();
    expect(camera.querySelector('.fullCoverage')).toBeNull();
    rerender(<CityMap {...props} site={{...site,sources:[{...pose,calibrationRevision:undefined}]}} />);
    expect(screen.queryByLabelText('Camera 01 · Camera · calibrated view direction')).not.toBeInTheDocument();
  });
  it('draws active regions after inactive regions from other cameras', () => {
    const rule: any = { id: 'active', sourceId: 'camera', kind: 'area-entry', name: 'Crossing area', enabled: true,
      geometry: { space: 'site-metres', points: [[1,1],[4,1],[4,4]] } };
    const { container } = render(<CityMap {...props} showAllRules rules={[rule, { ...rule, id: 'quiet', sourceId: 'other' }]}
      snapshot={{ ...snapshot, zones: [{ id: 'active', active: true }] as any }} />);
    const layers = Array.from(container.querySelectorAll('g.zone, g.activeZone'));
    expect(layers).toHaveLength(2); expect(layers[0]).toHaveClass('zone'); expect(layers[1]).toHaveClass('activeZone');
  });
  it('places a controlled static map in the calibrated bounds without adding simulated actors', () => {
    const { container } = render(<CityMap {...props} site={{ ...site, map: { ...site.map, imageUrl: '/smart-city/intersection.png' } }} />);
    const image = screen.getByLabelText('Static intersection map');
    expect(image).toHaveAttribute('href', '/smart-city/intersection.png');
    expect(image).toHaveAttribute('x', '0'); expect(image).toHaveAttribute('y', '0');
    expect(image).toHaveAttribute('width', '100'); expect(image).toHaveAttribute('height', '100');
    expect(container.querySelectorAll('[data-track]')).toHaveLength(2);
  });
  it('rejects external and traversal map image URLs', () => {
    const { rerender } = render(<CityMap {...props} site={{ ...site, map: { ...site.map, imageUrl: 'https://example.com/map.png' } }} />);
    expect(screen.queryByLabelText('Static intersection map')).not.toBeInTheDocument();
    rerender(<CityMap {...props} site={{ ...site, map: { ...site.map, imageUrl: '/smart-city/../private.png' } }} />);
    expect(screen.queryByLabelText('Static intersection map')).not.toBeInTheDocument();
  });
  it('extends the city backdrop and zoom range without changing the default view or observation coordinates', () => {
    const focus = { ...site, map: { ...site.map, bounds: [-55, 45, 10, 115] as [number, number, number, number], imageUrl: '/smart-city/isaac-intersection-a-map.png' } };
    const observed = { ...snapshot, tracks: [{ ...snapshot.tracks[0], positionM: [-22.5, 80] as [number, number] }] };
    const { container, rerender } = render(<CityMap {...props} site={focus} snapshot={observed} />);
    const initialView = screen.getByLabelText('Top-down camera observations in metres').getAttribute('viewBox');
    rerender(<CityMap {...props} site={{ ...focus, id: 'isaac-intersection-a' }} snapshot={observed} />);
    const image = screen.getByLabelText('Static intersection map');
    expect(image).toHaveAttribute('href', '/smart-city/isaac-intersection-a-map-wide.png');
    expect(image).toHaveAttribute('x', '-152.5'); expect(image).toHaveAttribute('y', '-60');
    expect(image).toHaveAttribute('width', '260'); expect(image).toHaveAttribute('height', '280');
    expect(screen.getByLabelText('Top-down camera observations in metres')).toHaveAttribute('viewBox', initialView);
    const marker = container.querySelector('[data-track="person"] .mapMarker');
    expect(marker).toHaveAttribute('cx', '-22.5'); expect(marker).toHaveAttribute('cy', '80');
    const zoomOut = screen.getByRole('button', { name: 'Zoom map out' });
    for (let n = 0; n < 8; n++) fireEvent.click(zoomOut);
    expect(zoomOut).toBeDisabled(); expect(container.querySelector('svg.mapCanvas > g')?.getAttribute('transform')).toContain('scale(0.25)');
    fireEvent.click(screen.getByRole('button', { name: 'Reset map view' }));
    expect(container.querySelector('svg.mapCanvas > g')?.getAttribute('transform')).toContain('scale(1)');
  });
  it('does not offer zoom controls or drag capture for an uncalibrated site', () => {
    render(<CityMap {...props} site={{ ...site, sources: [{ ...source, imageToGroundHomography: undefined }] }} snapshot={null} />);
    expect(screen.getByText('Connect the cameras to your site')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Zoom map in' })).not.toBeInTheDocument();
    const map = screen.getByLabelText('Top-down camera observations in metres'); const capture = jest.fn(); Object.defineProperty(map, 'setPointerCapture', { configurable: true, value: capture });
    fireEvent.pointerDown(map, { pointerId: 1, clientX: 20, clientY: 30 }); expect(capture).not.toHaveBeenCalled();
  });
  it('selects both person and vehicle observations with Space without scrolling', () => {
    const select = jest.fn(); render(<CityMap {...props} onSelect={select} />);
    for (const [name, id] of [['Person · Camera on map', 'person'], ['Car · Camera on map', 'car']]) {
      const target = screen.getByRole('button', { name }); const event = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
      fireEvent(target, event); expect(event.defaultPrevented).toBe(true); expect(select).toHaveBeenLastCalledWith(id);
    }
  });
  it('resets zoom after site bounds or identity change and on the reset control', () => {
    const { rerender, container } = render(<CityMap {...props} />);
    const transform = () => container.querySelector('svg.mapCanvas > g')?.getAttribute('transform');
    const initial = transform(); fireEvent.click(screen.getByRole('button', { name: 'Zoom map in' })); expect(transform()).toContain('scale(1.25)');
    fireEvent.click(screen.getByRole('button', { name: 'Reset map view' })); expect(transform()).toBe(initial);
    fireEvent.click(screen.getByRole('button', { name: 'Zoom map in' })); rerender(<CityMap {...props} site={{ ...site, map: { ...site.map, bounds: [-50, -50, 50, 50] } }} />); expect(transform()).toContain('scale(1)');
    fireEvent.click(screen.getByRole('button', { name: 'Zoom map in' })); rerender(<CityMap {...props} site={{ ...site, id: 'replacement' }} />); expect(transform()).toContain('scale(1)');
  });
  it('pans in the filled map coordinates and stops after capture is lost', () => {
    const { container, rerender } = render(<CityMap {...props} />); const map = screen.getByLabelText('Top-down camera observations in metres');
    Object.defineProperty(map, 'setPointerCapture', { configurable: true, value: jest.fn() });
    jest.spyOn(map, 'getBoundingClientRect').mockReturnValue({ width: 200, height: 100 } as DOMRect);
    const pointer = (type: string, clientX: number, clientY: number) => { const event = new MouseEvent(type, { bubbles: true, clientX, clientY }); Object.defineProperty(event, 'pointerId', { value: 1 }); fireEvent(map, event); };
    const pan = () => container.querySelector('svg.mapCanvas > g')!.getAttribute('transform')!.match(/^translate\(([^ ]+) ([^)]+)\)/)!.slice(1).map(Number);
    pointer('pointerdown', 10, 10); pointer('pointermove', 30, 20); expect(pan()[0]).toBeCloseTo(10.6); expect(pan()[1]).toBeCloseTo(5.3);
    fireEvent.lostPointerCapture(map); const stopped = pan(); pointer('pointermove', 50, 50); expect(pan()).toEqual(stopped);
    rerender(<CityMap {...props} site={{ ...site, id: 'replacement' }} />); expect(pan()).toEqual([0, 0]);
  });
  it('exposes one larger, keyboard-focusable target per observation and its selection state', () => {
    const select = jest.fn(); const { container } = render(<CityMap {...props} selectedTrack="person" onSelect={select} />);
    const person = screen.getByRole('button', { name: 'Person · Camera on map' });
    expect(person).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Car · Camera on map' })).toHaveAttribute('aria-pressed', 'false');
    const hit = person.querySelector('.mapHitTarget')!;
    expect(hit).toHaveAttribute('stroke-width', '24'); expect(hit).toHaveAttribute('vector-effect', 'non-scaling-stroke');
    fireEvent.click(hit); expect(select).toHaveBeenLastCalledWith('person');
    fireEvent.keyDown(person, { key: 'Enter' }); expect(select).toHaveBeenCalledTimes(2);
    expect(container.querySelectorAll('[data-track] [tabindex]')).toHaveLength(0);
  });
  it('never implies all observations are combined when only some have shared IDs', () => {
    render(<CityMap {...props} snapshot={{ ...snapshot, tracks: [snapshot.tracks[0], { ...snapshot.tracks[1], globalTrackId: 'shared-8' }] }} />);
    expect(screen.getByText('2 observations')).toBeInTheDocument();
    expect(screen.getByText('Camera-owned observations · overlap can show an object twice')).toBeInTheDocument();
    expect(screen.queryByText(/Camera observations combined/)).not.toBeInTheDocument();
  });
  it('ignores alternate buttons and secondary pointers without interrupting the first drag', () => {
    const { container } = render(<CityMap {...props} />); const map = screen.getByLabelText('Top-down camera observations in metres');
    const capture = jest.fn(); Object.defineProperty(map, 'setPointerCapture', { configurable: true, value: capture });
    jest.spyOn(map, 'getBoundingClientRect').mockReturnValue({ width: 100, height: 100 } as DOMRect);
    const pointer = (type: string, id: number, x: number, button = 0, primary = true) => {
      const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: 0, button });
      Object.defineProperties(event, { pointerId: { value: id }, isPrimary: { value: primary } }); fireEvent(map, event);
    };
    const transform = () => container.querySelector('svg.mapCanvas > g')!.getAttribute('transform');
    pointer('pointerdown', 1, 0, 2); pointer('pointermove', 1, 20); expect(capture).not.toHaveBeenCalled();
    pointer('pointerdown', 2, 0, 0, false); expect(capture).not.toHaveBeenCalled();
    pointer('pointerdown', 1, 0); pointer('pointerdown', 2, 10); pointer('pointermove', 2, 50);
    expect(transform()).toContain('translate(0 0)'); expect(capture).toHaveBeenCalledTimes(1);
    pointer('pointerup', 2, 50); pointer('pointermove', 1, 10); expect(Number(transform()!.match(/^translate\(([^ ]+)/)![1])).toBeCloseTo(10.6);
    pointer('pointercancel', 1, 10); const stopped = transform(); pointer('pointermove', 1, 20); expect(transform()).toBe(stopped);
  });

  it('explains grouped monitoring rules on hover, pins on keyboard selection and opens the measurement', () => {
    const onFocusRule = jest.fn(); const onInspectRule = jest.fn();
    const rule: any = { id: 'crossing', sourceId: 'camera', kind: 'occupancy-threshold', name: 'East crossing', enabled: true, classes: ['person'], conditions: {countThreshold: 2},
      geometry: { space: 'site-metres', points: [[1,1],[4,1],[4,4]] } };
    render(<CityMap {...props} rules={[rule]} onFocusRule={onFocusRule} onInspectRule={onInspectRule}><div>Automatic finding</div></CityMap>);
    const area = screen.getByRole('button', {name:'East crossing · Count area · monitoring area'});
    fireEvent.mouseEnter(area); expect(screen.getByLabelText('Map inspection')).toHaveTextContent('Counts people inside this area.');
    expect(screen.queryByText('Automatic finding')).not.toBeInTheDocument();
    fireEvent.mouseLeave(screen.getByLabelText('Calibrated live top-down map')); expect(screen.getByText('Automatic finding')).toBeInTheDocument();
    fireEvent.keyDown(area, {key:' '}); expect(onFocusRule).toHaveBeenCalledWith('crossing');
    expect(area).toHaveAttribute('aria-pressed','true');
    fireEvent.click(screen.getByRole('button', {name:'View measurement'})); expect(onInspectRule).toHaveBeenCalledWith('crossing');
    expect(screen.getByText('Automatic finding')).toBeInTheDocument();
  });
  it('keeps the scenario explanation visible when a visitor points at its area', () => {
    const rule: any = { id: 'crossing', sourceId: 'camera', kind: 'occupancy-threshold', name: 'East crossing', enabled: true, classes: ['person'], conditions: {},
      geometry: { space: 'site-metres', points: [[1,1],[4,1],[4,4]] } };
    render(<CityMap {...props} rules={[rule]} keepContextVisible><div>Scenario explanation</div></CityMap>);
    fireEvent.mouseEnter(screen.getByRole('button', { name: 'East crossing · Count area · monitoring area' }));
    expect(screen.getByText('Scenario explanation')).toBeInTheDocument();
    expect(screen.queryByLabelText('Map inspection')).not.toBeInTheDocument();
  });
  it('inspects calibrated camera coverage without stealing the drag gesture and clears for object selection', () => {
    const pose = {...source,calibrationRevision:'cal-1',cameraPositionWorldM:[12,0,8] as [number,number,number],groundCoverageM:[[10,10],[30,10],[30,30]] as [number,number][]};
    render(<CityMap {...props} site={{...site,sources:[pose]}}><div>Automatic finding</div></CityMap>);
    const pin = screen.getByRole('button', {name:'Inspect camera 01 · Camera'});
    const map = screen.getByLabelText('Top-down camera observations in metres'); const capture = jest.fn(); Object.defineProperty(map,'setPointerCapture',{value:capture});
    fireEvent.pointerDown(pin,{button:0,pointerId:1}); expect(capture).not.toHaveBeenCalled();
    fireEvent.focus(pin); expect(screen.getByLabelText('Map inspection')).toHaveTextContent('calibrated position');
    fireEvent.keyDown(pin,{key:'Enter'}); fireEvent.blur(pin); expect(screen.getByLabelText('Map inspection')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name:'Person · Camera on map'})); expect(screen.queryByLabelText('Map inspection')).not.toBeInTheDocument();
    expect(screen.getByText('Automatic finding')).toBeInTheDocument();
  });
  it('keeps the map key off the canvas until requested and lets a presenter hide monitoring areas', () => {
    const rule: any = {id:'line',sourceId:'camera',kind:'line-crossing',name:'Northbound',enabled:true,classes:['car'],conditions:{},geometry:{space:'site-metres',points:[[1,1],[4,1]]}};
    render(<CityMap {...props} rules={[rule]} />);
    expect(screen.getByText('Camera-owned observations · overlap can show an object twice')).not.toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:'Map key'})); expect(screen.getByText('Camera-owned observations · overlap can show an object twice')).toBeVisible();
    fireEvent.keyDown(screen.getByRole('button',{name:'Map key'}),{key:'Escape'}); expect(screen.getByText('Camera-owned observations · overlap can show an object twice')).not.toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:'Show monitoring areas'})); expect(screen.queryByRole('button',{name:/Northbound.*monitoring area/})).not.toBeInTheDocument();
  });

  it('previews an area without pinning, then clears a pin on blank map or outside clicks', () => {
    const preview=jest.fn(),clear=jest.fn(); const rule:any={id:'area',sourceId:'camera',kind:'occupancy-threshold',name:'Crossing',enabled:true,classes:['person'],conditions:{},geometry:{space:'site-metres',points:[[1,1],[4,1],[4,4]]}};
    render(<CityMap {...props} rules={[rule]} onPreviewRule={preview} onClearFocus={clear}/>);
    const area=screen.getByRole('button',{name:'Crossing · Count area · monitoring area'});
    fireEvent.mouseEnter(area);expect(preview).toHaveBeenLastCalledWith('area');expect(area).toHaveAttribute('aria-pressed','false');
    fireEvent.mouseLeave(area);expect(preview).toHaveBeenLastCalledWith(null);fireEvent.mouseEnter(area);
    fireEvent.click(area);fireEvent.mouseLeave(screen.getByLabelText('Calibrated live top-down map'));expect(preview).toHaveBeenLastCalledWith('area');
    fireEvent.click(screen.getByLabelText('Top-down camera observations in metres'));expect(clear).toHaveBeenCalledTimes(1);expect(preview).toHaveBeenLastCalledWith(null);expect(screen.queryByLabelText('Map inspection')).not.toBeInTheDocument();
    fireEvent.click(area);fireEvent.pointerDown(document.body);expect(clear).toHaveBeenCalledTimes(2);expect(area).toHaveAttribute('aria-pressed','false');
  });

});
