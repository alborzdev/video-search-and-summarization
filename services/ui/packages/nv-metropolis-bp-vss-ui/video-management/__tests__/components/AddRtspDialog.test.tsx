// SPDX-License-Identifier: MIT

import { AddRtspDialog } from "../../lib-src/components/AddRtspDialog";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

describe("AddRtspDialog accessibility", () => {
  const profiles = {
    profiles: [
      {
        description: "Semantic search without a detector.",
        detectionEnabled: false,
        id: "semantic-search",
        maxSources: 8,
        modelId: null,
        modelLabel: "Cosmos Embed + Cosmos Reason",
        name: "Semantic search + Vision Analyst",
        objectTypes: [],
        ready: true,
        readyDetail: "Shared semantic services",
        resourceTier: "low",
        ruleKinds: ["semantic"],
        sceneTypes: ["general"],
        shortName: "Search only",
      },
      {
        description: "Warehouse detection and tracking.",
        detectionEnabled: true,
        id: "warehouse-safety",
        maxSources: 8,
        modelId: "nvidia/rtdetr-warehouse-v1.0.2",
        modelLabel: "NVIDIA RT-DETR Warehouse",
        name: "Warehouse safety",
        objectTypes: ["Person", "Forklift", "Pallet"],
        ready: true,
        readyDetail: "Ready on NVIDIA Thor",
        resourceTier: "medium",
        ruleKinds: ["area-entry", "proximity"],
        sceneTypes: ["warehouse"],
        shortName: "Warehouse",
      },
    ],
  };

  it("associates its title and required field labels with the dialog controls", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      json: async () => profiles,
      ok: true,
      text: async () => JSON.stringify(profiles),
    });
    render(
      <AddRtspDialog
        isOpen
        agentApiUrl="http://127.0.0.1:8100"
        onClose={jest.fn()}
      />
    );

    expect(screen.getByRole("dialog", { name: "ADD LIVE CAMERA" })).toHaveAttribute(
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
    await screen.findByRole("radio", { name: /Semantic search/i });
  });

  it("defaults to resource-safe general analysis and can opt into the warehouse detector", async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({
        json: async () => profiles,
        ok: true,
        text: async () => JSON.stringify(profiles),
      })
      .mockResolvedValueOnce({
        json: async () => ({
          analysisProfileId: "warehouse-safety",
          detectionEnabled: true,
          name: "Warehouse Main",
          sensorId: "sensor-1",
          status: "success",
        }),
        ok: true,
        text: async () => "",
      });
    global.fetch = fetchMock;
    render(
      <AddRtspDialog
        isOpen
        agentApiUrl="http://thor.test/api/v1"
        onClose={jest.fn()}
      />
    );

    expect(await screen.findByRole("radio", { name: /Semantic search/i })).toBeChecked();
    fireEvent.click(
      screen.getByRole("radio", { name: /Warehouse safety/i })
    );
    fireEvent.change(screen.getByLabelText(/RTSP URL/), {
      target: { value: "rtsp://camera.test/main" },
    });
    fireEvent.change(screen.getByLabelText(/Sensor Name/), {
      target: { value: "Warehouse Main" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect camera" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toEqual(
      expect.objectContaining({
        analysisProfileId: "warehouse-safety",
        name: "Warehouse Main",
        sensorUrl: "rtsp://camera.test/main",
      })
    );
  });
});
