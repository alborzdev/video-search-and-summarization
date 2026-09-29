import { demoServiceChecks, type SystemHealth } from "../systemHealth";

const healthy: SystemHealth = {
  checkedAt: "2026-09-29T00:00:00Z",
  status: "online",
  services: ["video", "agent", "embedding", "vlm", "llm", "perception"].map((key) => ({
    key, label: key, latencyMs: 1, ok: true,
  })),
};

function statuses(health: SystemHealth) {
  return demoServiceChecks(health).map((check) => check.status);
}

describe("demo service availability", () => {
  it("keeps search and answers available when the detector is unavailable", () => {
    expect(statuses({ ...healthy, status: "degraded", services: healthy.services.map((service) => ({
      ...service, ok: service.key !== "perception",
    })) })).toEqual(["available", "available", "available", "unavailable"]);
  });

  it.each([
    ["video", ["unavailable", "unavailable", "unavailable", "unavailable"]],
    ["agent", ["available", "unavailable", "unavailable", "available"]],
    ["embedding", ["available", "unavailable", "available", "available"]],
    ["vlm", ["available", "available", "unavailable", "available"]],
    ["llm", ["available", "available", "unavailable", "available"]],
  ])("marks only affected actions unavailable when %s fails", (key, expected) => {
    expect(statuses({ ...healthy, services: healthy.services.map((service) => ({
      ...service, ok: service.key !== key,
    })) })).toEqual(expected);
  });

  it("does not infer readiness from missing checks or an aggregate online flag", () => {
    expect(statuses({ ...healthy, services: [] })).toEqual(["unknown", "unknown", "unknown", "unknown"]);
    expect(statuses({ ...healthy, services: [{ key: "video", label: "Video", ok: false, latencyMs: null }] }))
      .toEqual(["unavailable", "unavailable", "unavailable", "unavailable"]);
  });
});
