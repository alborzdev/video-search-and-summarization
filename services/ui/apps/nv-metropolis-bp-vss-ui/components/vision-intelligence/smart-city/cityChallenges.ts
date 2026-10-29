// SPDX-License-Identifier: MIT
/** Operational context only. These descriptions never supply analytics results. */
export interface CityChallenge {
  problem: string;
  observe: string;
  action: string;
  researchTitle: string;
  researchUrl: string;
}

export const CITY_CHALLENGES: Readonly<Record<string, CityChallenge>> = {
  'crossing-occupancy': {
    problem: 'A green signal does not tell you whether everyone has finished crossing.',
    observe: 'People inside one crossing, camera-observed occupied time, and peak occupancy.',
    action: 'Use observed crossing demand and occupied time to review pedestrian service.',
    researchTitle: 'Pedestrian service · FHWA',
    researchUrl: 'https://ops.fhwa.dot.gov/publications/fhwahop23041/fhwahop23041.pdf',
  },
  'queue-blockage': {
    problem: 'A queue can fill the junction and take away space for other movements.',
    observe: 'Confirmed stopped vehicles inside the junction, their observed duration, and the saved camera event.',
    action: 'Review the location, duration and camera event before adjusting traffic operations.',
    researchTitle: 'Queue management · FHWA',
    researchUrl: 'https://ops.fhwa.dot.gov/publications/fhwahop13031/chap2.htm',
  },
  'emergency-access': {
    problem: 'Stopped traffic inside a junction can prevent an ambulance from getting through.',
    observe: 'A stopped-junction event and its observed duration. The ambulance is scene context; emergency classification and dispatch are not automated.',
    action: 'Give the operator a saved camera incident to review and coordinate a response.',
    researchTitle: 'Queue management · FHWA',
    researchUrl: 'https://ops.fhwa.dot.gov/publications/fhwahop13031/chap2.htm',
  },
  'turning-demand': {
    problem: 'Changing traffic demand is hard to understand from a video wall.',
    observe: 'Completed camera-observed turns, with interrupted journeys kept separate.',
    action: 'Compare observed demand by movement, then review timing with the traffic team.',
    researchTitle: 'Turning-movement counts · UDOT',
    researchUrl: 'https://udottraffic.utah.gov/atspm/FAQs/Display',
  },
  'queue-recovery': {
    problem: 'Queues can use up approach storage and obstruct crossing access.',
    observe: 'Currently observed queue objects and available queue extent. Missing tracks stay marked.',
    action: 'Find the approach to investigate, then review its timing and storage.',
    researchTitle: 'Queue management · FHWA',
    researchUrl: 'https://ops.fhwa.dot.gov/publications/fhwahop13031/chap2.htm',
  },
  'pedestrian-service': {
    problem: 'People need enough time and clear space to cross.',
    observe: 'People in the approach and crossing, plus completed journeys when camera evidence supports them.',
    action: 'Review pedestrian demand and observed approach time with the traffic team.',
    researchTitle: 'Pedestrian service · FHWA',
    researchUrl: 'https://ops.fhwa.dot.gov/publications/fhwahop23041/fhwahop23041.pdf',
  },
  'curb-obstruction': {
    problem: 'Busy curb space can leave access unpredictable.',
    observe: 'Vehicles detected in the curbside area and their available observed dwell.',
    action: 'Investigate where and when access stays occupied before changing curb operations.',
    researchTitle: 'Code the Curb · USDOT / LADOT',
    researchUrl: 'https://www.transportation.gov/sites/dot.gov/files/2024-10/LADOT.pdf',
  },
  'crossing-obstruction': {
    problem: 'A stopped vehicle can take away crossing access.',
    observe: 'Stopped-vehicle evidence, observed duration and whether the observation clears.',
    action: 'Review the stopped-vehicle event and its footage, then decide the next operational action.',
    researchTitle: 'Crossing access · FHWA',
    researchUrl: 'https://highways.dot.gov/safety/pedestrian-bicyclist/pedestrian-safety-guide-transit-agencies/chapter-3-actions-increase',
  },
};

export function cityChallenge(id: string | null | undefined): CityChallenge | null {
  return id && Object.prototype.hasOwnProperty.call(CITY_CHALLENGES, id) ? CITY_CHALLENGES[id] : null;
}

export const TOPIC_CHALLENGE: Readonly<Record<string, string>> = {
  movements: 'turning-demand', queues: 'queue-recovery', crossings: 'pedestrian-service',
  curbs: 'curb-obstruction', obstructions: 'crossing-obstruction',
};
