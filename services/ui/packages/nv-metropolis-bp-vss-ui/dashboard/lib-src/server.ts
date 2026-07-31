// SPDX-License-Identifier: MIT
// Server-side data fetching for Dashboard component
// In production, replace this with actual API calls to your backend

import { env } from 'next-runtime-env';

const KIBANA_BASE_URL = env('NEXT_PUBLIC_DASHBOARD_TAB_KIBANA_BASE_URL') || process?.env?.NEXT_PUBLIC_DASHBOARD_TAB_KIBANA_BASE_URL;
// Browser-visible URLs often use the host ingress, while server-side rendering
// runs inside the UI container where 127.0.0.1 is the UI itself. Keep those
// authorities separate so SSR can discover dashboards without leaking an
// internal container address into the iframe rendered for operators.
const KIBANA_INTERNAL_URL =
  process?.env?.DASHBOARD_KIBANA_INTERNAL_URL || KIBANA_BASE_URL;
const ENABLE_DASHBOARD_TAB =
  (env('NEXT_PUBLIC_ENABLE_DASHBOARD_TAB') || process?.env?.NEXT_PUBLIC_ENABLE_DASHBOARD_TAB) !== 'false';
const DEFAULT_DASHBOARD_ID =
  env('NEXT_PUBLIC_DASHBOARD_TAB_DEFAULT_DASHBOARD_ID') ||
  process?.env?.NEXT_PUBLIC_DASHBOARD_TAB_DEFAULT_DASHBOARD_ID ||
  null;

const FETCH_TIMEOUT_MS = 5000; // 5 seconds timeout

async function fetchKibanaDashboards() {
  if (!KIBANA_INTERNAL_URL) {
    return [];
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    const response = await fetch(
      `${KIBANA_INTERNAL_URL}/api/saved_objects/_find?type=dashboard&fields=title&fields=description`,
      { signal: controller.signal }
    );

    clearTimeout(timeoutId);

    if (!response.ok) {
      console.error(`Failed to fetch dashboards: ${response.statusText}`);
      return [];
    }

    const data = await response.json();
    return data.saved_objects || [];
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      console.error('Fetch dashboards timed out after', FETCH_TIMEOUT_MS, 'ms');
    } else {
      console.error('Error fetching dashboards from Kibana:', error);
    }
    return [];
  }
}

export async function fetchDashboardData() {
  if (!ENABLE_DASHBOARD_TAB) {
    return {
      systemStatus: 'operational',
      kibanaBaseUrl: null,
      dashboards: [],
      defaultDashboardId: DEFAULT_DASHBOARD_ID,
    };
  }

  const dashboards = await fetchKibanaDashboards();

  return {
    systemStatus: 'operational',
    kibanaBaseUrl: KIBANA_BASE_URL || null,
    dashboards,
    defaultDashboardId: DEFAULT_DASHBOARD_ID,
  };
}
