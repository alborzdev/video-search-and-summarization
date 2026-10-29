# Pedestrian visibility and continuity audit — 26 October 2026

The zero west-waiting maximum in the two-second scenario poll was a sampling omission. Exact replay of 838 retained northeast observation frames reaches one waiting person for five frames between 30.944 and 31.473 seconds. It then records a 589.2 ms first-seen waiting lower bound. The wait rectangle contains the independently verified native waiting point; no misplaced ROI is established.

The native waiting/WALK-wait lasts much longer, yet no corresponding person is exported there until just before the crossing boundary. The southwest camera does not cover that point; northeast projection is inside its image. Without retained images, this audit cannot distinguish static occlusion, visibility or detector rejection. Simulator C02 positions remain a separately labelled reference and are never fed to analytics.

The exact [receipt](pedestrian-staged-visibility-continuity-audit.json) records why completion remains zero. Local handle 39336 has a 1.086111 second real-observation gap at 50.010–51.096 seconds; the 1 second continuity limit marks its journey incomplete. That same native handle returns, but later ends mid-crossing. Handle 39343 resumes there and ends at x −16.985, just before the −16.9 far boundary. Handle 39348 first appears at x −16.184, already outside. Neither a larger wait polygon nor a slightly longer same-ID gap can prove that final exit across changing local identities. The backend correctly avoids inventing a completed crossing.

The next concrete improvement is to inspect the waiting point and far edge in actual retained camera imagery and adjust scene/camera visibility if necessary. A separately measured ordinary NvDCF retention trial may help local continuity. Changing shadow age or analytics gaps without that evidence is not a complete fix. Keep pending/missing states honest and retain camera-local identity authority; no simulator IDs or geometric aliases should enter live analytics.

This was an isolated CPU replay of the actual `MobilitySpatial` code, using 1,676 retained native observations across both cameras and the unchanged rules/configuration. Source hashes, raw byte bounds, exact camera clocks and the separately labelled native endpoint receipt are in the JSON. It changes no source or runtime configuration.


## Retained camera images and framing review

The existing retained-media `/picture` service returned seven requested northeast camera images using CPU decoding, each in about 0.2–0.5 seconds. See [visual and candidate receipt](pedestrian-story-framing-review.json) for exact source times, hashes and image filenames. Waiting and late WALK-wait images contain no visible C02 at the projected position against the building façade; no vehicle covers that image location. A frame near native position (−36.125,66.833) is also blank there, whereas the next sampled position (−34.862,66.790) shows the person clearly. Moving the entry only to x −36.0 is therefore not a demonstrated fix.

The [far-boundary frame](pedestrian-visual-ne-row-31-crossing.jpg), taken when no corresponding local detection is present, shows the person clearly to the right of the pole. A later frame partly overlaps the pole after the new local handle is already detected. The pole is not sufficient evidence for the initial loss.

A review-only candidate uses entry (−36.0,67.6), midpoint (−26.2,67.6) and exit (−14.5,67.6), with the existing five-second hold and WALK gate. The actual native NavMesh query uses C02 radius 0.25515 m and height 1.82250 m and returns both path segments in 0.031 seconds. Its ground points pass the unchanged waiting/crossing membership and directional edge tests, and northeast projection remains valid. These are navigation/geometry checks, not visibility acceptance. Existing PhysX rays return no collider for old or new points and cannot establish render visibility. The survey's documented SW building extent also includes the proposed point.

Root must review any finite approach trial before accepting this candidate: verify native arrival separately, inspect the actual existing camera recording and detector observations during the hold, then cancel/restore if hidden or absent. No candidate, task, camera, threshold or runtime change was applied during this audit.
