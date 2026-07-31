// SPDX-License-Identifier: MIT
export declare function fetchDashboardData(): Promise<{
    systemStatus: string;
    kibanaBaseUrl: string | null;
    dashboards: Array<{
        id: string;
        attributes: {
            title: string;
            description?: string;
        };
    }>;
    defaultDashboardId: string | null;
}>;
