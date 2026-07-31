// SPDX-License-Identifier: MIT

jest.mock('next-runtime-env', () => ({
  env: (name: string) => process.env[name],
}));

describe('dashboard server data', () => {
  const originalFetch = global.fetch;
  const originalPublicUrl = process.env.NEXT_PUBLIC_DASHBOARD_TAB_KIBANA_BASE_URL;
  const originalInternalUrl = process.env.DASHBOARD_KIBANA_INTERNAL_URL;
  const originalDefaultDashboardId =
    process.env.NEXT_PUBLIC_DASHBOARD_TAB_DEFAULT_DASHBOARD_ID;

  afterEach(() => {
    global.fetch = originalFetch;
    if (originalPublicUrl === undefined) {
      delete process.env.NEXT_PUBLIC_DASHBOARD_TAB_KIBANA_BASE_URL;
    } else {
      process.env.NEXT_PUBLIC_DASHBOARD_TAB_KIBANA_BASE_URL = originalPublicUrl;
    }
    if (originalInternalUrl === undefined) {
      delete process.env.DASHBOARD_KIBANA_INTERNAL_URL;
    } else {
      process.env.DASHBOARD_KIBANA_INTERNAL_URL = originalInternalUrl;
    }
    if (originalDefaultDashboardId === undefined) {
      delete process.env.NEXT_PUBLIC_DASHBOARD_TAB_DEFAULT_DASHBOARD_ID;
    } else {
      process.env.NEXT_PUBLIC_DASHBOARD_TAB_DEFAULT_DASHBOARD_ID =
        originalDefaultDashboardId;
    }
    jest.resetModules();
  });

  it('fetches through the internal URL but returns the browser-visible URL', async () => {
    process.env.NEXT_PUBLIC_DASHBOARD_TAB_KIBANA_BASE_URL =
      'http://127.0.0.1:7777/kibana';
    process.env.DASHBOARD_KIBANA_INTERNAL_URL =
      'http://host.docker.internal:5601/kibana';
    process.env.NEXT_PUBLIC_DASHBOARD_TAB_DEFAULT_DASHBOARD_ID =
      'thor-vss-overview';
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        saved_objects: [{ id: 'dashboard-1', attributes: { title: 'Alerts' } }],
      }),
    } as Response);

    const { fetchDashboardData } = await import('../lib-src/server');
    const result = await fetchDashboardData();

    expect(global.fetch).toHaveBeenCalledWith(
      'http://host.docker.internal:5601/kibana/api/saved_objects/_find?type=dashboard&fields=title&fields=description',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.kibanaBaseUrl).toBe('http://127.0.0.1:7777/kibana');
    expect(result.dashboards).toHaveLength(1);
    expect(result.defaultDashboardId).toBe('thor-vss-overview');
  });
});
