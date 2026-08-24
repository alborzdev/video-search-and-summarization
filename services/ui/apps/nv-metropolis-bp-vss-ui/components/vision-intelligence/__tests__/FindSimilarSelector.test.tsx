// SPDX-License-Identifier: MIT

import { closestFrame, parseDetectedObjects } from "../FindSimilarSelector";

describe("FindSimilarSelector data handling", () => {
  it("keeps only valid detector boxes and preserves tracker identity", () => {
    expect(
      parseDetectedObjects([
        {
          bbox: { bottomY: 220, leftX: 10, rightX: 110, topY: 20 },
          id: "39",
          type: "Person",
        },
        {
          bbox: { bottom: 90, left: 8, right: 60, top: 12 },
          className: "Forklift",
          objectId: "7",
        },
        { id: "missing-box" },
        {
          bbox: { bottomY: 20, leftX: 20, rightX: 10, topY: 10 },
          id: "invalid-box",
        },
      ])
    ).toEqual([
      {
        bbox: { bottomY: 220, leftX: 10, rightX: 110, topY: 20 },
        id: "39",
        type: "Person",
      },
      {
        bbox: { bottomY: 90, leftX: 8, rightX: 60, topY: 12 },
        id: "7",
        type: "Forklift",
      },
    ]);
  });

  it("selects the nearest indexed frame instead of guessing the requested timestamp", () => {
    const result = closestFrame(
      {
        frames: [
          {
            objects: [
              {
                bbox: { bottomY: 40, leftX: 10, rightX: 30, topY: 10 },
                id: "far",
              },
            ],
            timestamp: "2025-01-01T00:01:49.800Z",
          },
          {
            objects: [
              {
                bbox: { bottomY: 60, leftX: 20, rightX: 50, topY: 20 },
                id: "nearest",
              },
            ],
            timestamp: "2025-01-01T00:01:50.033Z",
          },
        ],
      },
      "2025-01-01T00:01:50.000Z"
    );

    expect(result).toEqual({
      objects: [
        {
          bbox: { bottomY: 60, leftX: 20, rightX: 50, topY: 20 },
          id: "nearest",
          type: undefined,
        },
      ],
      timestamp: "2025-01-01T00:01:50.033Z",
    });
  });

  it("prefers the nearest frame containing the requested object class", () => {
    const result = closestFrame(
      {
        frames: [
          {
            objects: [
              {
                bbox: { bottomY: 80, leftX: 10, rightX: 70, topY: 20 },
                id: "forklift",
                type: "Forklift",
              },
            ],
            timestamp: "2025-01-01T00:01:45.000Z",
          },
          {
            objects: [
              {
                bbox: { bottomY: 100, leftX: 20, rightX: 60, topY: 30 },
                id: "person",
                type: "Person",
              },
            ],
            timestamp: "2025-01-01T00:01:45.233Z",
          },
        ],
      },
      "2025-01-01T00:01:45.000Z",
      "person"
    );

    expect(result).toEqual({
      objects: [
        {
          bbox: { bottomY: 100, leftX: 20, rightX: 60, topY: 30 },
          id: "person",
          type: "Person",
        },
      ],
      timestamp: "2025-01-01T00:01:45.233Z",
    });
  });
});
