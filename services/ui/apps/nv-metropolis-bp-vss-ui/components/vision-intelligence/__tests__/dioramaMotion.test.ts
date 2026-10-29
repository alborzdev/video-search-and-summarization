import { dioramaActors, DioramaCase } from "../smart-city/dioramaMotion";

it.each<DioramaCase>(["boarding", "crossing", "queue", "wrong-way"])(
  "keeps actor identities stable through %s and bounds playback",
  (scene) => {
    const before = dioramaActors(scene, 0);
    const after = dioramaActors(scene, 1);
    expect(after.map((a) => a.id)).toEqual(before.map((a) => a.id));
    expect(dioramaActors(scene, -1)).toEqual(before);
    expect(dioramaActors(scene, 2)).toEqual(after);
    for (const t of [0, 0.25, 0.5, 0.75, 1])
      for (const a of dioramaActors(scene, t)) {
        expect(Number.isFinite(a.x) && Number.isFinite(a.y)).toBe(true);
        expect(a.x).toBeGreaterThan(0);
        expect(a.x).toBeLessThan(1672);
        expect(a.y).toBeGreaterThan(0);
        expect(a.y).toBeLessThan(941);
      }
  }
);
it("turns the car toward the crossing and extends the queue while leading cars remain stopped", () => {
  expect(dioramaActors("crossing", 0)[0].turn).toBe(0);
  expect(dioramaActors("crossing", 1)[0].turn).toBe(1);
  const before = dioramaActors("queue", 0),
    after = dioramaActors("queue", 1);
  expect(after.slice(0, 2)).toEqual(before.slice(0, 2));
  expect(after[2].x).toBeGreaterThan(before[2].x);
});
