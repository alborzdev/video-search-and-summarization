import { readWorkloadAdmissionFacts } from "../../../server/vision/workloadAdmissionAdapter";

jest.mock("../../../server/vision/liveAlertReservation", () => ({ readActiveLiveAlertReservations: jest.fn(async () => []) }));
jest.mock("../../../server/vision/cosmosReservation", () => ({ readCosmosReservationState: jest.fn(() => ({ active: false, waitingCount: 0 })) }));

describe("Spark workload capacity adapter", () => {
  const original = { ...process.env };
  const originalFetch = global.fetch;
  afterEach(() => { process.env = { ...original }; global.fetch = originalFetch; });
  it.each(["fresh", "stale", "missing", "malformed"])("fails closed on %s capacity while avoiding Thor probes", async (sample) => {
    process.env.HARDWARE_PROFILE = "DGX-SPARK";
    process.env.HISTORY_METADATA_TOKEN = "test-local-token";
    process.env.SPARK_CAPACITY_URL = "http://capacity.test/capacity";
    const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/v1/health/ready")) return { ok: true } as Response;
      if (url.endsWith("/v1/stream/get-stream-info")) return { ok: true, json: async () => ({ stream_list: [] }) } as Response;
      if (url === "http://capacity.test/capacity") return { ok: sample !== "missing", json: async () => ({
        hardwareProfile: "DGX-SPARK", guardActive: true, reserveGiB: 24,
        availableGiB: sample === "malformed" ? "36" : 36,
        sampledAt: Date.now() / 1000 - (sample === "stale" ? 20 : 0),
      }) } as Response;
      throw new Error("Unexpected probe");
    });
    global.fetch = fetchMock;
    const facts = await readWorkloadAdmissionFacts();
    expect(facts.runtime).toBe("spark");
    expect(facts.sparkCapacity?.state).toBe(sample === "fresh" ? "fresh" : "unknown");
    expect(facts.telemetry).toEqual({ state: "unknown", gpuUtilizationPercent: null });
    const call = fetchMock.mock.calls.find(([url]) => String(url) === "http://capacity.test/capacity");
    expect(call).toBeDefined();
    expect(fetchMock).toHaveBeenCalledWith("http://capacity.test/capacity", expect.objectContaining({
      headers: { "X-History-Metadata-Token": "test-local-token" },
    }));
  });
});
