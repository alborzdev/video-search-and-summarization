// SPDX-License-Identifier: MIT
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { CityRuleEditor, ruleDraftError, type RuleDraft } from '../CityRuleEditor';
const draft: RuleDraft = { sourceId: 'cam1', name: 'Crossing', kind: 'line-crossing', classes: ['person'], points: [[.2, .5], [.8, .5]], direction: [0, -1], minimumDurationMs: 0, countThreshold: 1 };
describe('city directed line editor', () => {
  it('saves a complete directed line and reverses its direction', () => {
    const onChange = jest.fn(); const onSave = jest.fn();
    render(<CityRuleEditor draft={draft} onChange={onChange} onClose={jest.fn()} onSave={onSave} onDelete={jest.fn()} rules={[]} sources={[{ id: 'cam1', name: 'Crossing camera', width: 1920, height: 1080 }]} saving={false} error={null} onEdit={jest.fn()} />);
    fireEvent.click(screen.getByText('Reverse crossing direction'));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ direction: [-0, 1] }));
    fireEvent.click(screen.getByText('Save rule')); expect(onSave).toHaveBeenCalledTimes(1);
  });
  it('does not allow a polygon to save with two points', () => {
    render(<CityRuleEditor draft={{ ...draft, kind: 'occupancy' }} onChange={jest.fn()} onClose={jest.fn()} onSave={jest.fn()} onDelete={jest.fn()} rules={[]} sources={[]} saving={false} error={null} onEdit={jest.fn()} />);
    expect((screen.getByText('Save rule') as HTMLButtonElement).disabled).toBe(true);
  });
});

const sources = [{ id: 'cam1', name: 'Crossing camera', width: 1920, height: 1080 }];
const polygon: RuleDraft = { ...draft, kind: 'occupancy-threshold', points: [[.1,.1],[.8,.1],[.8,.8],[.1,.8]] };
const editorProps = { draft, onChange: jest.fn(), onClose: jest.fn(), onSave: jest.fn(), onDelete: jest.fn(), rules: [], sources, saving: false, error: null, onEdit: jest.fn() };
describe('rule edits and validation', () => {
  it('keeps a polygon when changing its rule type and resets only when geometry changes', () => {
    const onChange = jest.fn(); render(<CityRuleEditor {...editorProps} draft={polygon} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('Detection rule type'), { target: { value: 'dwell' } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'dwell', points: polygon.points }));
    fireEvent.change(screen.getByLabelText('Detection rule type'), { target: { value: 'line-crossing' } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'line-crossing', points: [] }));
  });
  it.each([
    ['fractional threshold', { countThreshold: 1.5 }, /whole object threshold/],
    ['too large threshold', { countThreshold: 10001 }, /whole object threshold/],
    ['missing threshold', { countThreshold: NaN }, /whole object threshold/],
    ['negative duration', { minimumDurationMs: -1 }, /trigger duration/],
    ['too long duration', { minimumDurationMs: 3600001 }, /trigger duration/],
    ['infinite duration', { minimumDurationMs: Infinity }, /trigger duration/],
    ['duplicate endpoints', { points: [[.2,.5],[.2,.5]] }, /distinct points/],
    ['extra line endpoint', { points: [[.2,.5],[.8,.5],[.9,.5]] }, /exactly two/],
    ['outside camera', { points: [[-.2,.5],[.8,.5]] }, /inside the camera/],
    ['missing direction', { direction: [0,0] }, /nonzero movement direction/],
    ['unknown source', { sourceId: 'other' }, /available camera/],
  ])('blocks %s with a useful explanation', (_name, change, message) => {
    render(<CityRuleEditor {...editorProps} draft={{ ...draft, ...change } as RuleDraft} />);
    expect(screen.getByRole('button', { name: 'Save rule' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent(message as RegExp);
  });
  it('rejects intersecting or collapsed polygons and accepts a concave polygon', () => {
    expect(ruleDraftError({ ...polygon, points: [[.1,.1],[.9,.8],[.1,.9],[.8,.1]] }, sources)).toMatch(/must not cross/);
    expect(ruleDraftError({ ...polygon, points: [[.1,.1],[.2,.2],[.3,.3]] }, sources)).toMatch(/with an area/);
    expect(ruleDraftError({ ...polygon, points: [[.1,.1],[.9,.1],[.4,.4],[.9,.9],[.1,.9]] }, sources)).toBeNull();
  });
  it('rejects small crossed polygons without rejecting small valid areas', () => {
    const small = (points: number[][]) => points.map(([x, y]) => [.5 + x * .005, .5 + y * .005] as [number, number]);
    expect(ruleDraftError({ ...polygon, points: small([[.1,.1],[.9,.8],[.1,.9],[.8,.1]]) }, sources)).toMatch(/must not cross/);
    expect(ruleDraftError({ ...polygon, points: small([[.1,.1],[.9,.1],[.4,.4],[.9,.9],[.1,.9]]) }, sources)).toBeNull();
  });
  it('leaves an empty number invalid rather than silently changing its meaning', () => {
    const onChange = jest.fn(); render(<CityRuleEditor {...editorProps} draft={polygon} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('Object threshold'), { target: { value: '' } });
    expect(onChange.mock.calls[0][0].countThreshold).toBeNaN();
    fireEvent.change(screen.getByLabelText('Trigger after (s)'), { target: { value: '1.25' } });
    expect(onChange.mock.calls[1][0].minimumDurationMs).toBe(1250);
  });
  it('locks draft mutations while saving but still allows closing the editor', () => {
    const onClose = jest.fn(); render(<CityRuleEditor {...editorProps} saving onClose={onClose} />);
    expect(screen.getByRole('button', { name: 'Close rule editor' })).toBeEnabled();
    for (const name of ['Rule camera', 'Rule name', 'Detection rule type', 'person']) expect(screen.getByLabelText(name)).toBeDisabled();
    for (const name of ['Reverse crossing direction', 'Undo point', 'Saving rule…']) expect(screen.getByRole('button', { name })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Close rule editor' })); expect(onClose).toHaveBeenCalledTimes(1);
  });
  it('clears delete confirmation when the edited rule changes', () => {
    const rule: any = { id: 'saved', name: 'Saved rule', kind: 'area-entry', enabled: true };
    const { rerender } = render(<CityRuleEditor {...editorProps} rules={[rule]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Delete Saved rule' }));
    expect(screen.getByRole('button', { name: 'Confirm deletion of Saved rule' })).toBeInTheDocument();
    rerender(<CityRuleEditor {...editorProps} rules={[rule]} draft={{ ...draft, id: 'another' }} />);
    expect(screen.queryByRole('button', { name: 'Confirm deletion of Saved rule' })).not.toBeInTheDocument();
  });
});
