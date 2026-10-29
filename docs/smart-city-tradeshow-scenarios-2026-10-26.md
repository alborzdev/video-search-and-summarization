# Smart City trade-show scenarios

Each scene asks an operations question, shows a scripted situation in Isaac Sim,
and presents measurements produced independently by the camera analytics. A
scene cue is not a detection. A missing or interrupted observation is shown as
waiting or incomplete rather than as a successful detection or clearance.

| Scenario | Operator question | Camera evidence | Why it helps |
| --- | --- | --- | --- |
| Turning traffic | Where does traffic go? | Completed camera-observed left, straight and right movements; interrupted journeys are separate. | Movement counts inform lane and signal-timing reviews. |
| Queue build-up | Where is traffic backing up? | Currently observed stopped vehicles and, when available, visible queue extent. | A queue's extent helps staff investigate approach storage. It is not automatically a spillback or confirmed clearance. |
| Pedestrian crossing | How are people using the crossing? | People observed in the approach and crossing; interrupted journeys are identified. | Crossing and waiting observations help staff review pedestrian service. They do not imply signal control or pedestrian intent. |
| Curb stop | Is curb access available? | Vehicles observed in the curbside area and observed dwell when available. | Staff can investigate how long access is occupied. A stop does not establish parking, loading or a violation. |
| Blocked crossing | Is the crossing blocked? | Confirmed stopped-vehicle episodes and their observed stopped-zone time. | Operators can find and review blocked access. This is not a crash or near-miss classifier. |

The question, scripted scene and camera-derived finding are labelled separately
in the overview. The map and camera views use only the selected scenario's
existing configured areas. A report must match the active scenario's identity,
analytics epoch and live camera coverage before it can be displayed; stale and
partial reports retain their uncertainty. Measurements use the available
camera view and are not a ground-truth census of the simulation.

Research anchors: the FHWA [signal timing manual](https://ops.fhwa.dot.gov/publications/fhwahop08024/chapter7.htm)
describes turning-movement counts for timing reviews; its [performance measures
chapter](https://ops.fhwa.dot.gov/publications/fhwahop08024/chapter3.htm) describes
queue length and approach storage. FHWA's [pedestrian guidance](https://highways.dot.gov/safety/pedestrian-bicyclist/pedestrian-safety-guide-transit-agencies/chapter-3-actions-increase)
discusses crossing and waiting time. USDOT's description of [Los Angeles's Code
the Curb](https://www.transportation.gov/sites/dot.gov/files/2024-10/LADOT.pdf)
explains the value of curb activity and availability information. These sources
provide operational context; they are not claims that this prototype controls
signals or performs enforcement.
