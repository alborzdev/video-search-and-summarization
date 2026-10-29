# Smart City mobility: operator and implementation note

Current deployment, October 23, 2026: two live cameras, rule revision **262**, mobility configuration **3**, and **14** enabled primitives. Exact processed previews are available at [Smart City on port 7782](http://127.0.0.1:7782/?workspace=smart-city). The source-mounted development UI and CPU analytics gateway contain this increment; no model/native image was rebuilt. See the [current deployment receipt](qa/smart-city-2026-10-23/curb-reliability-deployed-summary.json).

## Use the demo

1. Open **Insights**, choose the measurement topic, and select **1, 5 or 15 minutes**. Check camera coverage before interpreting a total. A new window starts with partial coverage.
2. Use **Show on map** to find a movement gate or crossing. **Show queue on map** displays the approach axis, spillback boundary and observed tail when available.
3. Open the **Configure insights** control to select existing rules for movements, crossings or queues. Use **Edit zones** to create or adjust the underlying camera rules first. Each measurement belongs to one camera.
4. For a queue, select its polygon and use **Draw queue axis on map**: click the two stop-line endpoints, then one point upstream. Set the spillback distance in metres and save. These three points define the measurement direction; they do not create a new road or change the simulation.
5. Use **Export CSV** or **JSON** for the selected window. Reports carry camera ownership, coverage and configuration. JSON retains the full structured report.

## Prepared measurements

| Measurement | Owner and behaviour |
| --- | --- |
| Three northbound movements | Southwest camera. A vehicle must cross the existing northbound entry gate, then the north, west or east exit gate to count as straight, left or right. Reports include class counts, completed and interrupted journeys, and observed travel time. |
| Northbound approach queue | Northeast camera. The preset stop line is at site Y=63.8 m and its upstream reference is at Y=50 m. At least two connected slow vehicle anchors must persist for 1,500 ms. The speed threshold is 0.35 m/s; anchor connection and stop-line reach limits are 8 m. Spillback is measured against a boundary 10 m upstream. The default maximum observation gap is 1,000 ms. |
| South crossing, west to east | Northeast camera. The west waiting polygon and south crosswalk form a pedestrian journey. Wait samples require observed waiting-area entry, followed by crossing entry. Completion requires a later observed far-side exit. First-seen-inside waits are excluded. |
| Crossing obstruction and line totals | Existing stopped-vehicle crossing rules provide two obstruction summaries. Enabled count lines supply camera-local totals automatically. Blocked time unions overlapping confirmed-active intervals, so two vehicles do not double the zone duration. |

The current preset adds eight measurement primitives to the six existing rules (14 total): movement gates, queue area, two pedestrian approach areas, a pedestrian corridor and a curb area. It uses exported **static** camera calibration, crosswalks and lane geometry. Simulator actor positions, identities, intended turns and signal phases are not analytics inputs. The helper is [isaac_mobility.py](../tools/smart-city/isaac_mobility.py); it preserves an existing operator measurement selection when restoring the preset rule geometry.

## Curb access and recovery increment

The **Curb access** topic adds a vehicle polygon with an operator-selected role: general curb, loading area, bus stop or cycle lane. The prepared scene uses **North arm · curbside access**, a general curbside traffic-lane zone at site Y=96–106 m. It is not a designated parking bay or bus stop, and the simulation choreography was not changed. Passing vehicles produce observed visits; persistent occupancy needs actual sustained presence.

Use **Configure insights → Curb areas** to select the camera and polygon, assign its role and set the persistent-occupancy threshold. The default is 30 seconds. **Show on map** locates the zone. The 1/5/15-minute report and exports include observed occupancy, occupied seconds, arrivals, departures/zone turnover, complete/partial/interrupted visits, completed-visit observed dwell and stopped-time evidence. Counts remain camera-local. Occupied time unions simultaneous visits. Stopped time is unavailable until valid velocity evidence exists.

An arrival requires an observed outside-to-inside transition. A departure requires an observed inside-to-outside transition. First seen inside starts a partial visit and creates no arrival. Short same-ID misses retain visit continuity within the configured gap, while missing intervals add no measured curb dwell or occupied time. Longer losses become incomplete once; they do not become departures. Fresh positive observations can be reported as lower bounds while missing membership remains unresolved. Current visible counts, pending membership and historical losses are distinct.

Queue/pedestrian recovery uses the existing observation-gap limits and speed thresholds. Brief missed detections no longer immediately end a pedestrian visit, and old lost IDs do not block new positive queue measurements forever. Loss evidence has a bounded 15-minute retention period. Expiry is not a confirmed clearance. First-seen waiting durations are lower bounds and stay separate from fully observed wait samples. An unavailable field means evidence is missing, not a measured zero.

For an existing prepared site, `python3 tools/smart-city/isaac_mobility.py --apply --add-curb --add-east-crossing` adds the default curb selection only if no curb measurement is already saved, preserving other saved measurement selections. Normal startup restores the preset geometry; it does not replace an existing operator curb selection.

### Pedestrian corridor and timing scope

The south pedestrian measurement uses a **corridor** covering the marked crossing plus 1.5 m on each long side. It counts road traversals adjacent to the markings as well as on-paint paths; it is not a painted-crosswalk compliance measure. The original painted-crossing obstruction polygons remain unchanged. The east approach area reaches 4 m beyond the south marking and 4 m toward the sidewalk, within the calibrated view. Both west-to-east and east-to-west measurement directions are configured.

The interface calls the duration **time before crossing**. It includes walking through the approach area and any waiting there. Stationary waiting and signal delay are not isolated by this increment. First-seen-inside durations are explicitly lower bounds, separate from samples with an observed approach entry. Completed crossings require a continuous same-ID observed entry and exit across the actual near/far corridor edges; an offset approach centroid no longer requires an exit beyond the farthest corner. Side and reverse exits are excluded.

A camera-only CPU replay of 6,500 original detector frames (373 s of source time) demonstrated observed curb transitions and one complete east-to-west corridor traversal. It produced first-seen minimum approach-time samples, not a validated full-arrival waiting-time distribution. No actor truth, recorded-image substitution or synthetic observations were supplied to the live service.

## How it is connected

`GET /api/v1/city/mobility?windowMinutes=1|5|15` returns counts, movements, obstructions, queues, pedestrian journeys, configuration issues and per-camera `coverage`.

`PUT /api/v1/city/mobility/config` saves `movements`, `crossings` and `queues`, with `expectedRevision` for concurrent-edit protection. Invalid references return 422; a stale revision returns 409. Settings persist under the independent SQLite key `mobility:<site-id>` and do not restart camera tracks or change native rules. Deleted or disabled references make their measurements unavailable.

Aggregation uses bounded in-memory source-time windows. Observation loss pauses continuity and leaves unresolved journeys or episodes unknown; it does not prove departure. Valid measured history remains available through a temporary wall-clock stall. Process, configuration, rule or source-session resets restart the rolling measurements.

## Interpret the results correctly

Camera **source time** is the measurement clock. It is not necessarily wall time or Isaac scenario time. Identities remain camera-local; overlapping views are not fused or deduplicated. Coverage measures received frame time, not detector recall.

Queue extent uses observed ground anchors, not full vehicle footprints. Occlusion or unresolved members can make extent a lower bound or unknown. Blocked seconds include only fresh, confirmed-active intervals after activation; candidate dwell and blind intervals are excluded. Pedestrian waiting is observed journey time, not signal delay. No signal-control or traffic-law conclusion is implied.

The backend passed **155 CPU/API tests in 4.12 seconds**, including gap, persistence, window, union-time and spatial integration checks; targeted UI checks were also performed. These are implementation checks, not a real-scene accuracy study or an endurance qualification. See the [backend source receipt](qa/smart-city-2026-10-23/source-only-mobility-backend.json) for hashes and evidence boundaries. Deployment evidence is maintained separately by the main task.

Movement configurations with one shared entry are alternative exits. Observing one exit resolves the other alternatives for that track. Separate sequential measurements need distinct entry rules. The final backend suite passed 160 tests in 4.29 seconds, including queue uncertainty scoped to the calibrated image region.

## Current short validation

227 CPU/API/launcher controls passed in 4.55 s; 30 scoped UI controls passed in 2.39 s; app TypeScript passed. The rendered live curb report recorded real arrivals, departures, occupied seconds and completed-visit dwell, and its CSV was downloaded and parsed. These are implementation/integration checks; detector/tracker recall, final-scene measurement accuracy and sustained booth operation remain unqualified.
