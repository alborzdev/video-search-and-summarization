import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CityAvatarControl } from '../CityAvatarControl';

const initial = { available: true, running: false, busy: false, canStart: true, active: 0, message: 'Ready' };
const response = (data: object, ok = true) => ({ ok, json: async () => data });
afterEach(() => jest.restoreAllMocks());

test('starts and stops real avatar controls, disabling duplicate clicks during the request', async () => {
  let complete: (value: unknown) => void = () => {};
  global.fetch = jest.fn().mockResolvedValue(response(initial))
    .mockImplementationOnce(async () => response(initial))
    .mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }))
    .mockResolvedValueOnce(response(initial));
  render(<CityAvatarControl />);
  const start = await screen.findByRole('button', { name: 'Start live avatars' });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start); fireEvent.click(start);
  expect(fetch).toHaveBeenCalledTimes(2);
  complete(response({ ...initial, running: true, active: 2, source_status: 'Receiving Anvil data' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Stop live avatars' }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  expect(JSON.parse((fetch as jest.Mock).mock.calls[1][1].body)).toEqual({ operation: 'start' });
  expect(JSON.parse((fetch as jest.Mock).mock.calls[2][1].body)).toEqual({ operation: 'stop' });
});

test('offline or unprepared city cannot start avatars', async () => {
  global.fetch = jest.fn().mockResolvedValue(response({ ...initial, canStart: false }));
  render(<CityAvatarControl />);
  expect(await screen.findByRole('button', { name: 'Start live avatars' })).toBeDisabled();
  expect(await screen.findByText(/Wait for city preparation/)).toBeInTheDocument();
});

test('transport failure clears actionable status and exposes recovery text', async () => {
  global.fetch = jest.fn().mockResolvedValueOnce(response(initial)).mockResolvedValueOnce(response({ error: 'Anvil controls unavailable' }, false));
  render(<CityAvatarControl />);
  const start = await screen.findByRole('button', { name: 'Start live avatars' });
  await waitFor(() => expect(start).toBeEnabled()); fireEvent.click(start);
  expect(await screen.findByText('Anvil controls unavailable')).toBeInTheDocument();
  expect(start).toBeDisabled();
});
