# Traffic-camera analytics: city demand and next features

Research date: October 23, 2026. This is a feature-selection recommendation. Movement counts, stopped-crossing summaries, queues and pedestrian journeys have since been implemented; see the [mobility operator note](smart-city-mobility-2026-10-23.md) for deployment and limits. The source-only fast-pass changes and deferred live qualification remain described in [the fast-pass report](qa/smart-city-2026-10-23/source-only-fast-pass.md).

## Decision

Prioritize measurable intersection operations and crossing service. The next increment should add time-binned movement counts, crossing-obstruction evidence and duration summaries. Follow with approach queues and spillback, then pedestrian waiting-to-cross journeys. Add curb/bus-stop analytics when the scene has suitable geometry and activity. Develop potential-conflict review separately after timing and geometry validation.

This is our engineering judgment based on explicit procurement, city deployments, pilots and current implementation gaps. It is not a complete global procurement census or proof that every city wants the same product. The examples are predominantly US agencies, with UK local-government evidence and the Barcelona event's published priorities.

## What buyers actually ask for

| Evidence | Documented need | Product implication | Evidence boundary |
| --- | --- | --- | --- |
| [Kirkland RFQ 38-24-PW, July 11, 2024, Attachment B p.28](https://www.kirklandwa.gov/files/sharedassets/public/v/1/finance-and-administration/business-opportunities/rfq-38-24-pw-kirkland-safety-action-plan.pdf) | Video analytics and summary reports for six intersections: vehicle/bicycle turns, crosswalk counts, conflict patterns and countermeasure recommendations. | Movement counts and reviewable safety reports address a stated purchase requirement. | A solicitation establishes demand, not contract award or effectiveness. |
| [NYC DOT, June 2, 2026](https://www.nyc.gov/html/dot/html/pr2026/cutting-edge-sensors-understand-use-streets.shtml) | Expand a 20-site street-sensor pilot to 100 locations; use multimodal movement data to assess street changes and space allocation. | Show counts by mode, movement paths and comparable period reports. | Expansion and intended uses; no causal crash-reduction result established here. |
| [Alexandria, updated February 2, 2024](https://www.alexandriava.gov/mobility/ai-road-safety-and-traffic-counts) | Lane counts, turn percentages and time an intersection is blocked; reuse existing video streams. | Queue/blocked-junction analytics and camera reuse fit our edge appliance. | Pilot evaluates accuracy and staff workflow. |
| [Greater Cambridge Partnership, April 15, 2024](https://www.gov.uk/algorithmic-transparency-records/greater-cambridge-partnership-smart-pedestrian-crossing-trial) | Pedestrian count, flow, density and waiting time to support responsive crossings. | Measure waiting-area-to-crossing journeys and crossing occupancy. | Limited trial; the record says the authority did not fund deployment. |
| [Intercity Transit/Lacey/WSDOT demonstration, 2026](https://www.intercitytransit.com/about-us/smart-sensors) | Counts, queues, speeds, delays and safety patterns; short event clips validate results. | Link each important event to evidence and aggregate recurring problems. | Demonstration intended to evaluate accuracy/reliability; no completed outcome inferred. |
| [NYC Curb Management Action Plan announcement, September 2023](https://www.nyc.gov/mayors-office/news/2023/09/mayor-adams-dot-commissioner-rodriguez-action-plan-innovative-tools-reimagine) | Reduce double parking and blocked access; collect curb-use data with sensors/cameras. | Occupancy, dwell, turnover and persistent stops in named curb zones. | Strategy and planned tools; not a validation of our detector or enforcement capability. |
| [Smart City Expo 2026 Mobility program](https://www.smartcityexpo.com/tracks-scewc/mobility/) | Vision Zero, safety across transport modes, data-driven mobility and curbside management. | Lead with crossing safety and useful movement information for transport decision-makers. | Event positioning is audience evidence, not a purchase specification. |

## Current implementation, checked against source

RF-DETR Medium and NvDCF produce six road-user classes and camera-local tracks. Seven generic rule types exist: area entry, line crossing, occupancy threshold, dwell, stopped-in-zone, queue and wrong-way. The actual Isaac scene configuration has two crossing occupancy rules, two stopped-vehicle crossing rules, a northbound count line and an intersection occupancy threshold.

Map/camera selection, trails, durable events, JSON/CSV export and five-second VLM questions already exist. They should not be presented as new feature gaps. The queue rule currently counts slow anchors in a polygon; it does not measure queue extent. Existing exports are events/current metrics rather than traffic-engineering reports with interval totals and coverage.

Relevant source: [rule models](../services/analytics/behavior-analytics/apps/city/models.py), [engine](../services/analytics/behavior-analytics/apps/city/engine.py), [Isaac integration](smart-city-isaac-integration.md), [as-built](smart-city-as-built.md).

## Recommended build order

### 1. Movement and crossing report

Answer: Which approaches and crossings are busiest, and how does demand change?

Add entry/exit gates, completed movement journeys, left/through/right counts by approach and class, and 1/5/15-minute totals. Include the number of valid observation seconds and interrupted journeys. A report should be useful for examining lane allocation or signal timing, while leaving engineering decisions with the operator.

Use one owner camera per measurement zone. A journey needs a continuous identity from entry to exit in that camera. Missing exits remain incomplete; do not guess a turn or sum duplicate overlapping views. Distinguish detected bicycle objects from validated cyclist counts, since a person and bicycle can be two detections of one traveler. Fine vehicle classes remain subject to local detector errors.

### 2. Crossing-obstruction evidence

Answer: Where do stopped vehicles obstruct crossings, how often, and for how long?

Extend the existing stopped-in-crossing rules with episode start/end, duration, supporting frames and repeat frequency by crossing. Aggregate zone blocked time as the union of valid intervals, so two vehicles present simultaneously do not double the minutes. Show ongoing episodes separately from completed episodes.

The existing ground anchor is not a vehicle footprint. Until overlap is validated, use wording such as "vehicle stopped in crossing zone" and provide review evidence. A moving vehicle passing through is not a stopped obstruction. Missing observations must not silently close an episode or establish clearance. This is an operational observation, not an automatic legal finding.

### 3. Approach queue and spillback

Answer: Which approach is backing up, and has its queue reached a critical boundary?

Add lane centreline, stop line, contiguous queue membership, observed tail position, persistence and upstream boundary crossing. Display estimated queue extent on the map, not merely a red count badge. A distant isolated stopped vehicle must not become the tail of a connected queue. If the tail leaves the field of view, show a lower bound/unknown extent rather than an exact length.

This helps an operator locate blocked approaches and choose footage or signal data to examine. It does not itself identify the cause or prove which signal change will resolve the queue.

### 4. Pedestrian waiting and crossing service

Answer: How many people are waiting to cross, how long do observed crossing journeys wait, and who is still crossing?

Define waiting areas and crosswalks. Recognize waiting-area entry followed by crossing entry and completed crossing. Show valid sample count, median/upper-percentile observed wait, current occupancy and incomplete journeys. People walking along a sidewalk or leaving a waiting area without crossing are separate outcomes.

Signal state is not currently ingested. We can measure observed waiting and occupancy; signal delay, clearance-end alerts, yielding and red-light events need phase/right-of-way evidence. Signal control is a separate integration.

### 5. Curb and transit access

Answer: How is a loading area or bus stop being used, and when is access persistently occupied?

Add arrival, departure, dwell, turnover and occupied time for named zones when both camera coverage and the scenario support them. A bus arriving at an occupied stop is an understandable demonstration. Bus route reliability needs schedules/AVL data; vehicle class alone does not establish route, loading activity, permission or a parking violation.

## Safety analytics: valuable, but requires a separate evidence standard

Kirkland's purchase scope supports conflict screening. However, low temporal separation does not by itself prove a near miss. A [2023 study of PennDOT intersection data](https://arxiv.org/html/2307.13178v1) reviewed 1,470 selected events with post-encroachment time below three seconds; 89 were confirmed conflicts. These are results for that sampled dataset, not a universal error rate.

An eventual review feature should show the two trajectories, timing, location, evidence clip, screening reason and confirmed/dismissed status. Post-encroachment time measures the interval between users occupying the same conflict location. Time to collision depends on motion assumptions. Neither is a crash probability. Validate timestamps, sampling, tracking, ground projection and footprint geometry before using these as headline metrics. Compare events with observed exposure, rather than raw event totals alone.

## Timing and overlap constraints

The saved Isaac runs in the integration report advanced scenario time at approximately 0.35–0.39 times wall time while capture timestamps advanced at wall rate. This is historical evidence, not a new runtime measurement. Define and expose the metric time base before adding speed, waiting, flow or signal metrics. Video-time measurements must not be described as nominal scenario-time traffic behavior.

MV3DT remains disabled. Calibration and camera overlap do not establish shared identity. Keep per-zone measurement ownership explicit, and count unknown/incomplete observations separately. No live tests, service changes or scene edits were performed for this research.

## UI and edge-device story

Keep the two cameras and map central. The analysis area should answer a selected city question: crossing access, approach queues or movement demand. Use plain statements connected to the actual zone, interval and evidence. Put configuration behind controls. VLM answers can explain recorded measurements and cite events; they should not manufacture counts or causal conclusions from prose.

The commercial demonstration is an edge device turning existing camera streams into useful local measurements, events and reports. [Boston's Smart Streets project](https://content.boston.gov/departments/transportation/smart-streets-0) explicitly describes pole-mounted local analysis and aggregated output; it is an architecture precedent, not evidence of our current performance. Show actual measured processing delay and system health when available. Bandwidth reduction, privacy properties and WAN-independent operation must match what we implement and test.

Priority comes from city need, available evidence and a feature's ability to support a decision. Visual improvements should make those measurements and their limitations easier to understand. New models and extra dashboard panels are justified when they enable one of these tasks.
