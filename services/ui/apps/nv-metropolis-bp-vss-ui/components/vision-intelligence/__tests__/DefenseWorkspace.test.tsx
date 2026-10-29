// SPDX-License-Identifier: MIT
import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { DefenseWorkspace } from '../DefenseWorkspace';
import { createPreviewReport, snapshotFor } from '../defense/fixtures';

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
});
describe('Defense workspace isolation and workflows', () => {
  it('registers a review flow without treating a sample answer as inference', () => {
    render(<DefenseWorkspace onOpenSources={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name:'Acknowledge', exact:true }));
    expect(screen.getByText('Acknowledged · preview')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name:'Review evidence', exact:true }));
    expect(screen.getByText('Example response · not generated')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Connect footage to ask the analyst')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name:'Create incident report' }));
    const dialog = screen.getByRole('dialog', { name:'Preview report draft' });
    fireEvent.change(within(dialog).getByRole('textbox', { name:'Analyst notes' }), { target:{ value:'Check the gate log.' } });
    expect(within(dialog).getByDisplayValue('Check the gate log.')).toBeInTheDocument();
    expect(within(dialog).getByText(/not saved to operational reports/)).toBeInTheDocument();
  });
  it('removes preview observations and reports when switching data mode', () => {
    render(<DefenseWorkspace onOpenSources={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name:'Review evidence', exact:true }));
    fireEvent.click(screen.getByRole('button', { name:'Create incident report' }));
    fireEvent.change(screen.getByRole('combobox', { name:'Defense data mode' }), { target:{ value:'disconnected' } });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('No observations available')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name:'Review evidence', exact:true })).not.toBeInTheDocument();
    expect(screen.queryByText('Example response · not generated')).not.toBeInTheDocument();
  });
  it('makes collection dependency explicit instead of fabricating a successful flight', () => {
    render(<DefenseWorkspace onOpenSources={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name:'Drone inspection', exact:true }));
    fireEvent.click(screen.getByRole('button', { name:'Inspect finding', exact:true }));
    fireEvent.click(screen.getByRole('button', { name:'Request another view' }));
    expect(screen.getByRole('dialog', { name:'Request another view' })).toHaveTextContent('No drone or camera command has been sent');
  });
  it('does not show a stale rear frame as an unavailable front camera', () => {
    render(<DefenseWorkspace onOpenSources={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name:'Vehicle awareness', exact:true }));
    fireEvent.click(screen.getByRole('button', { name:'Front right Not connected', exact:true }));
    const title = screen.getByText('Front right camera');
    expect(title.closest('section')).toHaveTextContent('No camera connected');
    expect(within(title.closest('section')!).queryByRole('img')).not.toBeInTheDocument();
    expect(screen.queryByText('Person behind vehicle')).not.toBeInTheDocument();
  });
  it('routes source management through the existing shell callback', () => {
    const onOpenSources = jest.fn();
    render(<DefenseWorkspace onOpenSources={onOpenSources} />);
    fireEvent.click(screen.getByRole('button', { name:'Defense source readiness' }));
    fireEvent.click(screen.getByRole('button', { name:'Open existing camera management' }));
    expect(onOpenSources).toHaveBeenCalledTimes(1);
  });
  it('exports provenance and notes and refuses disconnected report creation', () => {
    expect(snapshotFor('disconnected').evidence).toEqual([]);
    expect(createPreviewReport('disconnected','site','')).toBeNull();
    const report = createPreviewReport('preview', 'drone', 'Inspect manually', new Date('2026-10-22T14:00:00Z'))!;
    expect(report.provenance).toBe('illustrative');
    expect(report.analystNotes).toBe('Inspect manually');
    expect(report.evidence.map(item => item.id)).toEqual(['pass','close']);
    expect(report.evidence.every(item => item.kind === 'illustrative' && !item.clipUrl)).toBe(true);
  });
});
