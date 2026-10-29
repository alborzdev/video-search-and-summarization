// SPDX-License-Identifier: MIT
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { LocalVisionInspector } from '../LocalVisionInspector';
import { prepareUploadedImage } from '../localVisionImage';
jest.mock('../localVisionImage', () => ({ prepareUploadedImage: jest.fn(), prepareDisplayedImage: jest.fn() }));
const prepared = { url: 'data:image/jpeg;base64,aGVsbG8=', base64: 'aGVsbG8=', name: 'frame.jpg' };
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
});
beforeEach(() => { (prepareUploadedImage as jest.Mock).mockResolvedValue(prepared); });
function response(value: unknown, ok = true) { return { ok, json: async () => value }; }
async function inputImage() { fireEvent.change(screen.getByLabelText('Upload image for local vision'), { target: { files: [new File(['image'], 'frame.jpg', { type: 'image/jpeg' })] } }); await screen.findByRole('img', { name: 'Input: frame.jpg' }); }
it('sends an actual selected image with point grounding and shows an empty result without a mask', async () => {
  global.fetch = jest.fn().mockResolvedValueOnce(response({ ready: true })).mockResolvedValueOnce(response({ operation: 'segment', status: 'no_detections', objects: [], timings_ms: { total: 340 } }));
  render(<LocalVisionInspector onClose={jest.fn()} />); await screen.findByText('Ready on this device'); await inputImage();
  fireEvent.change(screen.getByRole('textbox', { name: 'Object to find' }), { target: { value: 'aircraft' } }); fireEvent.click(screen.getByRole('button', { name: 'Run segment' }));
  await screen.findByText('No objects found for this prompt.');
  expect(JSON.parse((global.fetch as jest.Mock).mock.calls[1][1].body)).toEqual({ task: 'segment', image_base64: prepared.base64, object: 'aircraft', grounded_by: 'point', presence: 'off' });
  expect(screen.getByText('Request')).toBeInTheDocument(); expect(screen.queryByLabelText('Predicted object mask')).not.toBeInTheDocument();
});
it('shows real point coordinates and clears old results when the prompt changes', async () => {
  global.fetch = jest.fn().mockResolvedValueOnce(response({ ready: true })).mockResolvedValueOnce(response({ operation: 'point', status: 'ok', points: [{ point: [.25, .6] }], timings_ms: { total: 300 } }));
  render(<LocalVisionInspector onClose={jest.fn()} />); await screen.findByText('Ready on this device'); await inputImage();
  fireEvent.click(screen.getByRole('button', { name: 'Point', exact: true })); fireEvent.change(screen.getByRole('textbox', { name: 'Object to find' }), { target: { value: 'person' } }); fireEvent.click(screen.getByRole('button', { name: 'Run point' }));
  await screen.findByText('1 point returned'); expect(screen.getByLabelText('Point 1')).toHaveStyle({ left: '25%', top: '60%' });
  fireEvent.change(screen.getByRole('textbox', { name: 'Object to find' }), { target: { value: 'vehicle' } }); expect(screen.queryByLabelText('Point 1')).not.toBeInTheDocument();
});
it('blocks inference while unavailable and exposes busy errors on a request', async () => {
  global.fetch = jest.fn().mockResolvedValueOnce(response({ ready: false, status: 'warming' }, false)).mockResolvedValueOnce(response({ ready: true })).mockResolvedValueOnce(response({ error: 'Local vision is busy. Retry shortly.' }, false));
  render(<LocalVisionInspector onClose={jest.fn()} />); await screen.findByText('Models loading'); expect(screen.getByRole('button', { name: 'Run segment' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Check local vision readiness' })); await screen.findByText('Ready on this device'); await inputImage();
  fireEvent.click(screen.getByRole('button', { name: 'Describe', exact: true })); fireEvent.click(screen.getByRole('button', { name: 'Run describe' }));
  await screen.findByRole('alert'); expect(screen.getByRole('alert')).toHaveTextContent('busy');
  expect(JSON.parse((global.fetch as jest.Mock).mock.calls[2][1].body)).toEqual({ task: 'describe', image_base64: prepared.base64 });
});
it('reports image preparation failures without sending inference', async () => {
  global.fetch = jest.fn().mockResolvedValue(response({ ready: true })); (prepareUploadedImage as jest.Mock).mockRejectedValue(new Error('Choose an image with no more than 16 million pixels.'));
  render(<LocalVisionInspector onClose={jest.fn()} />); await screen.findByText('Ready on this device');
  fireEvent.change(screen.getByLabelText('Upload image for local vision'), { target: { files: [new File(['x'], 'large.png', { type: 'image/png' })] } });
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('16 million pixels')); expect(global.fetch).toHaveBeenCalledTimes(1);
});

it('sends box grounding when selected and clears the result when guidance changes', async () => {
  global.fetch = jest.fn().mockResolvedValueOnce(response({ ready: true })).mockResolvedValueOnce(response({ operation: 'segment', status: 'ok', objects: [{box:[.2,.3,.7,.8]}] }));
  render(<LocalVisionInspector onClose={jest.fn()} />); await screen.findByText('Ready on this device'); await inputImage();
  fireEvent.click(screen.getByRole('button', {name:'Box guidance'}));
  fireEvent.change(screen.getByRole('textbox', {name:'Object to find'}), {target:{value:'pothole'}});
  fireEvent.click(screen.getByRole('button', {name:'Run segment'}));
  await screen.findByText('1 mask returned');
  expect(JSON.parse((global.fetch as jest.Mock).mock.calls[1][1].body)).toMatchObject({grounded_by:'detect',object:'pothole'});
  fireEvent.click(screen.getByRole('button', {name:'Point guidance'}));
  expect(screen.queryByLabelText('Detection 1')).not.toBeInTheDocument();
});
