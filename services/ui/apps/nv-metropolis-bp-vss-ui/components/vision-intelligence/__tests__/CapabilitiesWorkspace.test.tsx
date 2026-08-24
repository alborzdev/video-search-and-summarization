// SPDX-License-Identifier: MIT

import { CapabilitiesWorkspace } from "../CapabilitiesWorkspace";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";

describe("CapabilitiesWorkspace", () => {
  it("launches each guided demo at the product surface it promises", () => {
    const onExplore = jest.fn();
    const onOpenEvents = jest.fn();
    const onOpenLive = jest.fn();
    const onOpenRules = jest.fn();

    render(
      <CapabilitiesWorkspace
        onExplore={onExplore}
        onOpenEvents={onOpenEvents}
        onOpenLive={onOpenLive}
        onOpenRules={onOpenRules}
        systemHealth={null}
      />
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Try semantic search" })
    );
    expect(onExplore).toHaveBeenCalledWith(
      "Find the most important recent activity."
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Visual language understanding/ })
    );
    fireEvent.click(screen.getByRole("button", { name: "Ask a live source" }));
    expect(onOpenLive).toHaveBeenCalledWith("focused");

    fireEvent.click(
      screen.getByRole("button", { name: /Live edge intelligence/ })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Open live monitoring" })
    );
    expect(onOpenLive).toHaveBeenCalledWith("grid");

    fireEvent.click(screen.getByRole("button", { name: /Evidence synthesis/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "Build an evidence set" })
    );
    expect(onExplore).toHaveBeenCalledWith(
      "Show activity that may need operator review."
    );

    fireEvent.click(screen.getByRole("button", { name: /Video history/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "Open source history" })
    );
    expect(onOpenLive).toHaveBeenCalledWith("history");

    fireEvent.click(screen.getByRole("button", { name: /Verified alerts/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "Configure alert rules" })
    );
    expect(onOpenRules).toHaveBeenCalledTimes(1);
    expect(onOpenEvents).not.toHaveBeenCalled();
  });
});
