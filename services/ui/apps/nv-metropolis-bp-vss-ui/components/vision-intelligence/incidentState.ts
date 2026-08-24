// SPDX-License-Identifier: MIT

export type IncidentWorkflowState = "new" | "acknowledged" | "resolved";

export interface IncidentStateRecord {
  incidentId: string;
  state: IncidentWorkflowState;
  updatedAt: string;
}
