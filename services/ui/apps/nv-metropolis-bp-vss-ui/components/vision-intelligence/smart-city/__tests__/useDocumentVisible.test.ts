// SPDX-License-Identifier: MIT
import { act, renderHook } from '@testing-library/react';
import { useDocumentVisible } from '../useDocumentVisible';

it('tracks visibility changes and releases its listener on unmount', () => {
  const visibility = jest.spyOn(document, 'visibilityState', 'get');
  const remove = jest.spyOn(document, 'removeEventListener');
  visibility.mockReturnValue('visible');
  const { result, unmount } = renderHook(() => useDocumentVisible());
  expect(result.current).toBe(true);
  act(() => { visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')); });
  expect(result.current).toBe(false);
  act(() => { visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')); });
  expect(result.current).toBe(true);
  unmount();
  expect(remove).toHaveBeenCalledWith('visibilitychange', expect.any(Function));
  visibility.mockRestore(); remove.mockRestore();
});
