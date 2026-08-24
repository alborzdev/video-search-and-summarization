// SPDX-License-Identifier: MIT

import type { PrimarySection } from '../components/vision-intelligence/types';

const PRIMARY_SECTIONS: readonly PrimarySection[] = [
  'home',
  'live',
  'monitoring',
  'explore',
  'events',
  'capabilities',
  'system',
];

type QueryValue = string | string[] | undefined;
type WorkspaceQuery = Record<string, QueryValue>;

export function parseWorkspace(value: QueryValue): PrimarySection {
  const candidate = Array.isArray(value) ? value[0] : value;
  return PRIMARY_SECTIONS.includes(candidate as PrimarySection)
    ? (candidate as PrimarySection)
    : 'home';
}

/**
 * Creates a deterministic, shareable URL for the primary workspace while
 * retaining unrelated query parameters (for example, existing integrations).
 */
export function workspaceHref(
  workspace: PrimarySection,
  query: WorkspaceQuery = {}
): string {
  const params = new URLSearchParams();
  params.set('workspace', workspace);

  Object.keys(query)
    .filter((key) => key !== 'workspace')
    .sort()
    .forEach((key) => {
      const value = query[key];
      const values = Array.isArray(value) ? value : [value];
      values.forEach((item) => {
        if (typeof item === 'string') params.append(key, item);
      });
    });

  return `/?${params.toString()}`;
}
