// SPDX-License-Identifier: MIT

import { parseWorkspace, workspaceHref } from '../../utils/workspaceRoute';

describe('workspaceRoute', () => {
  it('accepts only known primary workspaces', () => {
    expect(parseWorkspace('monitoring')).toBe('monitoring');
    expect(parseWorkspace(['live', 'system'])).toBe('live');
    expect(parseWorkspace('unknown')).toBe('home');
    expect(parseWorkspace(undefined)).toBe('home');
  });

  it('creates a stable workspace URL while retaining unrelated query values', () => {
    expect(
      workspaceHref('events', { source: 'dock-2', workspace: 'home', view: ['all', 'open'] })
    ).toBe('/?workspace=events&source=dock-2&view=all&view=open');
  });
});
