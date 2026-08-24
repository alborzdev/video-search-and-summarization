// SPDX-License-Identifier: MIT

export interface InitialVisionPageData {
  alertsData: unknown | null;
  searchData: unknown | null;
  videoManagementData: unknown | null;
}

type DataFetcher = () => Promise<unknown>;

export const emptyInitialVisionPageData = (): InitialVisionPageData => ({
  alertsData: null,
  searchData: null,
  videoManagementData: null,
});

function settledValue(result: PromiseSettledResult<unknown>): unknown | null {
  return result.status === 'fulfilled' ? result.value : null;
}

/**
 * Fetch independent workspace data without making a single unavailable
 * backend erase useful data from the remaining workspaces.
 */
export async function getInitialVisionPageData({
  alerts,
  search,
  videoManagement,
}: {
  alerts: DataFetcher;
  search: DataFetcher;
  videoManagement: DataFetcher;
}): Promise<InitialVisionPageData> {
  const [alertsResult, searchResult, videoManagementResult] =
    await Promise.allSettled([alerts(), search(), videoManagement()]);

  return {
    alertsData: settledValue(alertsResult),
    searchData: settledValue(searchResult),
    videoManagementData: settledValue(videoManagementResult),
  };
}
