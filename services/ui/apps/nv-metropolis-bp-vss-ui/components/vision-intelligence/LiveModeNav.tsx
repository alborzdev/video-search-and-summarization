// SPDX-License-Identifier: MIT

import type { ReactNode } from "react";
import React from "react";

export type LiveMode = "monitor" | "activity" | "insights" | "rules";

interface LiveModeNavProps {
  active: LiveMode;
  action?: ReactNode;
  onSelect: (mode: LiveMode) => void;
}

export function LiveModeNav({ active, action, onSelect }: LiveModeNavProps) {
  return (
    <nav className="vi-subnav vi-live-mode-nav" aria-label="Monitoring views">
      {(
        [
          ["monitor", "Live cameras"],
          ["activity", "Events & reports"],
          ["insights", "Insights"],
          ["rules", "Alert rules"],
        ] as const
      ).map(([mode, label]) => (
        <button
          className={active === mode ? "is-active" : ""}
          type="button"
          aria-current={active === mode ? "page" : undefined}
          key={mode}
          onClick={() => onSelect(mode)}
        >
          {label}
        </button>
      ))}
      {action && <div className="vi-live-mode-action">{action}</div>}
    </nav>
  );
}
