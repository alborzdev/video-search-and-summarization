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

function holdInspection() {
  let release!: () => void;
  let markStarted!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const started = new Promise<void>((resolve) => { markStarted = resolve; });
  const operation = withCosmosReservation(async () => { markStarted(); await held; return "active"; });
  return { operation, release, started };
}

test("removes abandoned requests across an eight-hour session without running them later", async () => {
  jest.useFakeTimers();
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ stream_list: [] }) })) as jest.Mock;
  const held = holdInspection();
  await held.started;
  try {
    for (let hour = 0; hour < 8; hour++) {
      const controller = new AbortController();
      const inspection = jest.fn(async () => "expired");
      const pending = withCosmosReservation(inspection, controller.signal);
      expect(readCosmosReservationState().waitingCount).toBe(1);
      controller.abort();
      await expect(pending).rejects.toMatchObject({ statusCode: 504 });
      jest.advanceTimersByTime(60 * 60 * 1000);
      expect(inspection).not.toHaveBeenCalled();
      expect(readCosmosReservationState()).toEqual({ active: true, waitingCount: 0 });
    }
    const next = withCosmosReservation(async () => "next");
    held.release();
    await expect(held.operation).resolves.toBe("active");
    await expect(next).resolves.toBe("next");
    expect(readCosmosReservationState()).toEqual({ active: false, waitingCount: 0 });
  } finally { held.release(); await held.operation; jest.useRealTimers(); }
});

test("rejects queue overflow while preserving FIFO and a single active model operation", async () => {
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ stream_list: [] }) })) as jest.Mock;
  const held = holdInspection();
  await held.started;
  const order: number[] = [];
  const waiting = [1, 2, 3].map(index => withCosmosReservation(async () => { order.push(index); return index; }));
  try {
    const excess = jest.fn(async () => 4);
    await expect(withCosmosReservation(excess)).rejects.toMatchObject({ statusCode: 503 });
    expect(excess).not.toHaveBeenCalled();
    expect(readCosmosReservationState()).toEqual({ active: true, waitingCount: 3 });
    held.release();
    await held.operation;
    await expect(Promise.all(waiting)).resolves.toEqual([1, 2, 3]);
    expect(order).toEqual([1, 2, 3]);
    expect(readCosmosReservationState().active).toBe(false);
  } finally { held.release(); await held.operation; await Promise.all(waiting); }
});

test("expires queued evidence analysis even when its active predecessor stalls", async () => {
  jest.useFakeTimers();
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ stream_list: [] }) })) as jest.Mock;
  const held = holdInspection();
  await held.started;
  try {
    const inspection = jest.fn(async () => "late");
    const pending = withCosmosReservation(inspection);
    const failure = expect(pending).rejects.toMatchObject({ statusCode: 503 });
    jest.advanceTimersByTime(30_000);
    await failure;
    expect(readCosmosReservationState().waitingCount).toBe(0);
    held.release();
    await held.operation;
    expect(inspection).not.toHaveBeenCalled();
  } finally { held.release(); await held.operation; jest.useRealTimers(); }
});

test("does not reserve or touch captions for a request that already expired", async () => {
  global.fetch = jest.fn();
  const controller = new AbortController();
  controller.abort();
  await expect(withCosmosReservation(async () => "late", controller.signal)).rejects.toMatchObject({ statusCode: 504 });
  expect(global.fetch).not.toHaveBeenCalled();
  expect(readCosmosReservationState().active).toBe(false);
});
