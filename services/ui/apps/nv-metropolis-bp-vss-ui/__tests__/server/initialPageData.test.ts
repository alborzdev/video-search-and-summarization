// SPDX-License-Identifier: MIT

import { getInitialVisionPageData } from '../../server/vision/initialPageData';

describe('getInitialVisionPageData', () => {
  it('retains successful workspace data when another backend fails', async () => {
    await expect(
      getInitialVisionPageData({
        alerts: async () => ({ total: 2 }),
        search: async () => {
          throw new Error('search unavailable');
        },
        videoManagement: async () => ({ vstApiUrl: 'http://vst' }),
      })
    ).resolves.toEqual({
      alertsData: { total: 2 },
      searchData: null,
      videoManagementData: { vstApiUrl: 'http://vst' },
    });
  });
});
