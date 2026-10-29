// SPDX-License-Identifier: MIT
/** Booth narrative: authored events, with a separately identified real local mask. */
export const defenseBeats = [
  {
    label: "Defense / Vision at the edge",
    title: "One airfield.\nThree ways to see more.",
    body: "Follow the drone, the gate camera and the vehicle. See how each view becomes a useful local result.",
    outcome: "Three camera systems. Three useful results.",
    detail:
      "Explore the missions to see where the cameras, compute and operator fit.",
  },
  {
    label: "01 / Airfield recovery",
    title: "Start with the drone.\nFollow its camera.",
    body: "The drone surveys damaged pavement. Its video reaches Anvil at the ground station.",
    outcome: "A finding linked to its source image.",
    detail:
      "A camera can show visible damage. An engineer still determines the condition and next action.",
  },
  {
    label: "01 / From image to finding",
    title: "Keep that view.\nReveal the damage.",
    body: "In the same camera image, outline the depression. Keep the finding and source together for the engineer.",
    outcome: "An inspection finding the engineer can check.",
    detail:
      "Real local mask on an AI-generated image. The mask covers the depression, not every crack or loose fragment.",
  },
  {
    label: "02 / Site watch",
    title: "Now move to\nthe hangar gate.",
    body: "On the same airfield, a fixed camera watches the hangar boundary. Local AI can bring an entry to the security team.",
    outcome: "The entry event and the camera that explains it.",
    detail:
      "Detection plus tracking and a zone rule can flag entry. Access permission needs a separate source.",
  },
  {
    label: "02 / Review the event",
    title: "Same camera.\nOne event to review.",
    body: "Put the entry image, camera and event time in one place. The operator decides whether to respond.",
    outcome: "A focused review instead of another feed to watch.",
    detail:
      "Authored example event. A still image alone cannot prove a crossing; live entry rules require a video sequence.",
  },
  {
    label: "03 / Vehicle visibility",
    title: "Follow the road\nto the vehicle.",
    body: "The truck has its own cameras and local compute. The rear view reveals a person behind it.",
    outcome: "The relevant camera, with the reason to look.",
    detail:
      "Driver assistance: the operator remains in control. This does not establish distance or automatic braking.",
  },
  {
    label: "03 / Know your coverage",
    title: "Keep the person\nin view.",
    body: "Keep the rear view easy to inspect. A lost camera must look unavailable, never safe.",
    outcome: "A visible person cue and an explicit coverage state.",
    detail:
      "Illustrated rear camera. Camera-loss control is a UI demonstration, not a live fault-injection test.",
  },
  {
    label: "04 / Why local compute",
    title: "Pull back.\nConnect the results.",
    body: "Each camera system processes video near its operator. Remote sharing can wait when the uplink is down.",
    outcome: "Local review now. Selected evidence shared later.",
    detail:
      "Architecture illustration. Local power, camera links and models must remain available. No network is changed by this control.",
  },
  {
    label: "05 / Build the system",
    title: "One pattern.\nThree deployments.",
    body: "Use Anvil-T5 to bring camera input, AI processing and local evidence into one deployable system.",
    outcome: "Choose the camera system your customer needs.",
    detail:
      "Current model demo: DGX Spark. Anvil-T5 is the Jetson Thor deployment target; camera integration and performance require testing.",
  },
] as const;
export const defenseGroups = [
  ["Overview", 0],
  ["Airfield", 1],
  ["Site watch", 3],
  ["Vehicle", 5],
  ["Why Anvil", 7],
] as const;
export const defenseSources = [
  {
    name: "AFIT · September 2026",
    title: "Airfield damage assessment with small drones",
    text: "AFIT is researching how small drones can help engineers assess airfield damage faster and from a safer distance. This supports the inspection job; it does not validate our AI or authorize runway clearance.",
    url: "https://www.afit.edu/EN/news.cfm?article=0360410F7B",
  },
  {
    name: "U.S. Army · July 2025",
    title: "AI video analytics for installation security",
    text: "A Blue Grass Army Depot demonstration included AI video analytics and integrated security technologies. This supports camera triage and operator review as a real procurement topic.",
    url: "https://www.army.mil/article/287276/technology_demonstration_showcases_innovations_set_to_incorporate_into_huntsville_center_electronic_security_contracts",
  },
  {
    name: "Rheinmetall · November 2023",
    title: "Rear safety cameras for 359 Warrior vehicles",
    text: "A UK Ministry of Defence contract covers rear cameras so drivers can recognize terrain and personnel behind the vehicle. This proves demand for the view; the benefit of our AI cue still needs evaluation.",
    url: "https://www.rheinmetall.com/en/media/news-watch/news/2023/11/2023-11-21-rheinmetall-delivers-trailblazer-to-uk",
  },
  {
    name: "U.S. Army · January 2023",
    title: "Operations with unreliable connectivity",
    text: "The Army describes disconnected, intermittent and low-bandwidth conditions. Local processing is relevant when a workflow cannot depend on a remote cloud connection.",
    url: "https://www.army.mil/article/263153/army_to_implement_new_cybersecurity_approach_to_safeguard_network?trk=article-ssr-frontend-pulse_little-text-block",
  },
  {
    name: "Connect Tech · Anvil-T5",
    title: "The physical camera-to-compute connection",
    text: "Anvil-T5 is a Jetson Thor system with Ethernet and GMSL camera options. Select the camera board, power integration, storage and software for the actual installation. Interface counts do not establish AI throughput.",
    url: "https://connecttech.com/ftp/pdf/CTIM-ESG625_Manual.pdf",
  },
] as const;
