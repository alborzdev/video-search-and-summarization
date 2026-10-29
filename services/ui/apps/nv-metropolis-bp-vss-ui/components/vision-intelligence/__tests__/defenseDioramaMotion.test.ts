import { defenseWorldFrame } from "../defense/defenseDioramaMotion";

it("keeps context and detail on the same framing, then returns to the whole site", () => {
  expect(defenseWorldFrame(1)).toEqual(defenseWorldFrame(2));
  expect(defenseWorldFrame(3)).toEqual(defenseWorldFrame(4));
  expect(defenseWorldFrame(5)).toEqual(defenseWorldFrame(6));
  expect(defenseWorldFrame(7)).toEqual(defenseWorldFrame(0));
});
it("moves continuously between missions and clamps invalid progress", () => {
  const a = defenseWorldFrame(2),
    b = defenseWorldFrame(3),
    mid = defenseWorldFrame(2.5);
  expect(mid.x).toBeGreaterThan(b.x);
  expect(mid.x).toBeLessThan(a.x);
  expect(defenseWorldFrame(-5)).toEqual(defenseWorldFrame(0));
  expect(defenseWorldFrame(Infinity)).toEqual(defenseWorldFrame(0));
  expect(defenseWorldFrame(99)).toEqual(defenseWorldFrame(8));
});
