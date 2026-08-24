// SPDX-License-Identifier: MIT

jest.mock("../../../server/vision/liveAlertReservation", () => ({
  isSourceLiveAlertFocused: jest.fn().mockResolvedValue(false),
}));

import {
  readCosmosReservationState,
  withCosmosReservation,
} from "../../../server/vision/cosmosReservation";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  jest.restoreAllMocks();
});

test("releases the queue when caption restoration reporting throws", async () => {
  const fetchMock = jest
    .fn()
    .mockResolvedValueOnce({
      json: async () => ({
        stream_list: [
          {
            camera_id: "camera-a",
            camera_name: "Camera A",
            inference_active: true,
          },
        ],
      }),
      ok: true,
    })
    .mockResolvedValueOnce({ ok: true, status: 204 })
    .mockResolvedValueOnce({ ok: false, status: 503 })
    .mockResolvedValueOnce({
      json: async () => ({ stream_list: [] }),
      ok: true,
    });
  global.fetch = fetchMock as unknown as typeof fetch;

  const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {
    throw new Error("logger unavailable");
  });

  await expect(withCosmosReservation(async () => "first")).rejects.toThrow(
    "logger unavailable"
  );
  expect(readCosmosReservationState()).toEqual({
    active: false,
    waitingCount: 0,
  });

  errorSpy.mockRestore();
  await expect(withCosmosReservation(async () => "second")).resolves.toBe(
    "second"
  );
  expect(fetchMock).toHaveBeenCalledTimes(4);
});
