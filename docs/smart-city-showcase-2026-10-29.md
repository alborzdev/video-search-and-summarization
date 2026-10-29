# Three current-camera booth scenarios

The live shelf replaces the five earlier demos with three buttons. Clicking a
button loads and plays its scene. Clicking a different button during playback
covers the view, restores the old scene, then prepares and plays the selection.
Both cameras must present fresh frames from the new observation scope before
the view is revealed. Scenarios keep both full camera frames visible, with no
automatic zoom, crop or camera layout change.

| Button | Visible situation | VSS measurement |
| --- | --- | --- |
| Crossing occupied | Four native pedestrians cross the East crossing in two close pairs. | One named painted-crossing area; current people, continuous occupied time, peak occupancy and a saved camera event. |
| Queue → blockage | Eight cars travel north toward an existing roadwork barricade and cones at the exit. The queue grows back into the junction. | Confirmed stopped vehicles inside the junction, blocked time, peak count and saved events. |
| Emergency access | Traffic builds across a waiting yellow ambulance's route, then the ambulance proceeds after both queues clear. | Cross-traffic blockage, confirmed duration, saved incident IDs and a retained scene report. |

Vehicle scenes reveal the clear starting junction for two seconds before
releasing traffic. The loaded cars start behind the approach crossings,
with spacing that lets visitors watch them arrive. Native route motion,
car-following, signal and body-clearance gates move every vehicle; there are no
visible pose placements. The queue scenario has no owned vehicle stops: a
real downstream roadwork obstacle and native car-following produce the queue.
The barricade and cones are existing, loaded city props, restored to their
original session state after the run. The scene completes after the roadwork and
every body that blocked the junction have verified clearance, followed by five
seconds of camera observation. Remaining approach cars continue in normal
traffic. The emergency scenario retains two lead stops and a twelve-second
observation hold. Both use the coherent shared signal clock; cancellation
restores all owned controls.

VSS independently progresses from clear, through checking stopped evidence,
to a confirmed blockage and saved events. Native phase labels never generate
an alert or a timer. The emergency ROI covers the NS cross-traffic corridor,
excluding the waiting ambulance so it cannot count as its own obstruction.

The ambulance is scripted scene context. VSS does not claim emergency-vehicle
classification, dispatch or signal control. All displayed counts and durations
come from source-camera observations. Missing intervals do not advance timers;
interrupted coverage stays marked in the saved report. Native actor poses,
arrivals and vehicle departure receipts control the presentation only.

The areas use the unchanged static camera calibration. The East crossing
polygon was traced against the orthographic map and checked against both live
images; the older XW_E navigation survey extends beyond the painted crossing.
The Northeast camera owns the crossing count because it shows the people much
larger in its full frame. Image ROIs use the road plane so their camera and map
outlines agree. The North approach queue starts beyond the crosswalk/stop line,
and the two blockage areas stay inside the junction. Only the current scene's
areas appear; operator-created rules are preserved. The reviewed migration and
backup are handled by `tools/smart-city/prepare_showcase.py`.

The cached ambulance is warmed during native city preparation, with capture
fully detached. Scene playback reuses loaded vehicles and native walkers. It
keeps the existing native path, body, signal, arrival, capture and restoration
gates. A new prepared pedestrian cohort may join its own verified WALK admission;
it cannot bypass a red signal or an earlier pedestrian still crossing.

The earlier rehearsal claim that four native arrivals proved four visible
walkers was incorrect. The October 29 recording reproduced one smooth walker
and three agents frozen at their starts before jumping to their waypoints.
Prepared placement now calls native `reset` rather than `teleport` alone, which
resets stale locomotion state while the preparation cover is up. Four people
walk in two files inside the painted strip, then fan out onto four verified
sidewalk endpoints. Native navigation, body clearance and WALK gates remain.

Visual recheck at 15:05 UTC: four walkers visible on the paint, peak camera count
4, 18.56 seconds observed occupancy, no observation gaps, and a saved event.
Queue recheck: peak 2 approach vehicles, 5 stopped junction vehicles, 17.26 seconds
observed blockage, and saved events. Emergency recheck: the visible ambulance
waited for both queues, drove through, and the scene restored normal traffic at
61.9 seconds. The retained camera report has peak 6 stopped vehicles, 39.20 seconds
observed blockage, six event IDs and a final clear state; gaps remain explicitly
marked. These are rehearsal observations, not accuracy/latency guarantees.
Screenshots and separate camera/native receipts are in
`docs/qa/smart-city-scenario-alignment-2026-10-29/`.

Select **Review scene report** after completion to review the retained
measurements or export their JSON. Archived reports remain separate from the
current traffic. Camera-event review uses an actual retained evidence interval
when one is available.

The prior pedestrian-turn queue was replaced after review because it often
left only one vehicle in the junction and did not clearly explain spillback.
The revised roadwork scenario uses the existing full camera views, with the
downstream closure in view and vehicles approaching straight through the
junction. Two October 29 rehearsals (18:36–18:40 UTC) observed at least two
stopped vehicles in the junction, saved camera events, and restored normal
traffic at 70.8 and 76.0 seconds from preparation. The cameras recorded 27.8
and 29.2 seconds of blockage with observation gaps explicitly marked. The
first camera flag appeared about 30–35 seconds after the click. These are observations,
not a latency or detection guarantee. Receipts and screenshots are in
`/tmp/vss-queue-roadwork-2026-10-29/`.

An intermittent on-screen loss of detections was traced to the browser clearing
the overlay as soon as a video frame arrived before its matching metadata. This
was observed even when the VLM was idle. The follow-up audit replaced the
single pending image with a bounded queue of raw images keyed by exact RTP
timestamp (1.5-second age limit, at most 24 images and 32 MiB per camera).
Late metadata can therefore match the actual captured pixels across several
video callbacks. Playback never moves backwards to an older source sequence.

The last exact pair stays visible through transient metadata, health and
connection retries. After two seconds without a current pair, it is explicitly
labelled paused, removed from live map measurements and VLM capture, and kept
on screen while reconnecting. Recovery needs at least three valid pairs over
200 ms. Session, configuration and analytics-scope changes still invalidate
obsolete pixels immediately, including during reconnect backoff.

Routine state refreshes preserve active readers and cannot roll newer streamed
observations back to an older HTTP response. Missing health data does not
switch an established WebRTC reader to JPEG. The UI proxy handles slow socket
writes with pause/resume backpressure, bounded by 8 MiB and a five-second drain
deadline. Temporary lease-renewal failures retry within the existing lease.
The detector banner reports worker state independently of preview readiness.
Preparation covers also wait for current matched frames from both cameras after
cancellation, failed preparation and normal-traffic restoration.
These changes preserve real camera evidence; they do not fabricate detections
or guarantee uninterrupted delivery under a backend or network failure.

The same audit found a crossing preparation blocker: native retry can retain a
failed pre-entry attempt while the walker waits at its original curb. Showcase
selection now recognizes that historical attempt only with a matching terminal
failure receipt and unchanged entry, command and program. Accepted or moving
crossings, road occupancy, leases, body clearance and signal gates remain
protected. The showcase/prepared regression suites pass 69 tests.
The 19:04 UTC rehearsal passed preparation, showed four people in the crossing,
saved a camera event and displayed a real VLM description. Both camera views
remained visible through late metadata, and normal traffic restored afterward.
