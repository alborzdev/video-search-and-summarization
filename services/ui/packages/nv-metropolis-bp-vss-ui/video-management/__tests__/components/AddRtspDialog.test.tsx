// SPDX-License-Identifier: MIT

import { AddRtspDialog } from "../../lib-src/components/AddRtspDialog";
import { render, screen } from "@testing-library/react";
import React from "react";

describe("AddRtspDialog accessibility", () => {
  it("associates its title and required field labels with the dialog controls", () => {
    render(
      <AddRtspDialog
        isOpen
        agentApiUrl="http://127.0.0.1:8100"
        onClose={jest.fn()}
      />
    );

    expect(screen.getByRole("dialog", { name: "ADD RTSP" })).toHaveAttribute(
      "aria-modal",
      "true"
    );
    const urlInput = screen.getByLabelText(/RTSP URL/);
    const sensorInput = screen.getByLabelText(/Sensor Name/);
    const usernameInput = screen.getByLabelText("Username");
    const passwordInput = screen.getByLabelText("Password");
    expect(urlInput.tagName).toBe("INPUT");
    expect(urlInput).toHaveAttribute("id", "add-rtsp-url");
    expect(urlInput).toHaveAttribute("aria-required", "true");
    expect(sensorInput.tagName).toBe("INPUT");
    expect(sensorInput).toHaveAttribute("id", "add-rtsp-sensor-name");
    expect(sensorInput).toHaveAttribute("aria-required", "true");
    expect(usernameInput).toHaveAttribute("autocomplete", "username");
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(passwordInput).toHaveAttribute("autocomplete", "current-password");
  });
});
