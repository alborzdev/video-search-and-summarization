import s from "./VssIndustryScenes.module.css";
import {
  IconArrowRight,
  IconShieldCheck,
  IconChecklist,
  IconBell,
  IconCar,
  IconX,
} from "@tabler/icons-react";
import React, { useState } from "react";

export const industryBeats = [
  [
    "In practice / Warehouse safety",
    "A crossing worth a closer look.",
    "A forklift and a pedestrian share a crossing. Which interactions deserve review?",
  ],
  [
    "Warehouse safety / Investigate",
    "Find the interaction. Review the context.",
    "Use a proximity candidate to retrieve the clip and distinguish routine movement from a possible near miss.",
  ],
  [
    "In practice / Manufacturing",
    "Did the required check happen before packing?",
    "Compare visible work against the expected process, while the source footage is still easy to inspect.",
  ],
  [
    "Manufacturing / Verify the sequence",
    "Make the work sequence visible.",
    "Bring inspection and packing moments together so an operator can verify their order.",
  ],
  [
    "In practice / Retail operations",
    "A spill should not wait for a complaint.",
    "Watch customer walkways for a visible hazard, then give staff the scene and location.",
  ],
  [
    "Retail operations / Respond",
    "From a visible spill to a useful alert.",
    "A candidate points staff to the right aisle. They verify the hazard, protect the area and arrange cleanup.",
  ],
  [
    "In practice / Smart cities",
    "One stopped vehicle. A growing queue.",
    "A stationary vehicle can deserve attention when surrounding traffic starts moving.",
  ],
  [
    "Smart cities / Incident review",
    "See what stayed still as traffic moved.",
    "Track vehicle motion over time. Use configured duration thresholds to surface a possible stalled vehicle.",
  ],
  [
    "Your operation",
    "Start with the moment that matters to you.",
    "Different environments. The same idea: turn video into evidence your team can use.",
  ],
] as const;
const cases = [
  {
    sector: "WAREHOUSE SAFETY",
    name: "Pedestrian–forklift interactions",
    place: "Distribution center · crossing",
    image: "logistics",
    icon: IconShieldCheck,
    accent: "#a8e4ce",
    question: "Show the forklift–pedestrian interaction.",
    observation: "A crossing interaction to inspect.",
    action:
      "Review the full clip before classifying a near miss. Use confirmed events to improve the crossing layout.",
    benefit: "Review the important interactions.",
    pipeline: ["Proximity candidate", "Clip review", "Safety review"],
    sourceTitle: "Documented VSS workflow",
    sourceText:
      "NVIDIA’s warehouse alerting service retrieves proximity-event clips and uses a visual model to distinguish near misses from routine interactions. This illustration is a candidate, not a confirmed near miss.",
    source:
      "https://docs.nvidia.com/vss/3.2.0/warehouse-docs/alerting-service.html",
    sourceLabel: "NVIDIA VSS · Warehouse alerting",
    boundary:
      "Requires configured detection, tracking and incident review. No calibrated distance or collision-prevention claim.",
    alt: "Illustrative distribution center with a forklift approaching a pedestrian crossing",
  },
  {
    sector: "MANUFACTURING",
    name: "Assembly and process verification",
    place: "Workcell · inspection and packing",
    image: "manufacturing",
    after: "manufacturing",
    icon: IconChecklist,
    accent: "#b7cdef",
    question: "Was inspection visible before packing?",
    observation: "Inspection → packing. Check the sequence.",
    action:
      "Review the ordered clips against the required procedure; investigate missing or unclear steps before the unit moves on.",
    benefit: "Make process checks traceable.",
    pipeline: [
      "Expected procedure",
      "Ordered observations",
      "Operator verification",
    ],
    sourceTitle: "Real customer example · Pegatron",
    sourceText:
      "Pegatron’s VSS Assembly Guiding Agent helps verify assembly procedures and alerts workers to potential missed steps, such as a forgotten screw. The inspection-and-packing sequence here is illustrative, not Pegatron footage.",
    source:
      "https://www.nvidia.com/en-us/case-studies/pegatron-scales-factory-operations-with-visual-ai-digital-twins/",
    sourceLabel: "NVIDIA customer story · Pegatron",
    boundary:
      "Task-specific camera views, models and procedure validation are required. Visible inspection does not prove internal product quality.",
    alt: "Illustrative technician examining a machined housing under an inspection lamp",
  },
  {
    sector: "RETAIL OPERATIONS",
    name: "Spill and walkway hazard response",
    place: "Store floor · produce aisle",
    image: "retail",
    icon: IconBell,
    accent: "#e7cb99",
    question: "Watch for spills in customer walkways.",
    observation: "Visible liquid in the aisle.",
    action:
      "A staff member verifies the location, protects the area and arranges cleanup. Keep the incident clip for follow-up.",
    benefit: "Give staff a specific place to act.",
    pipeline: ["Visual condition", "Incident clip", "Staff response"],
    sourceTitle: "Established visual-AI application",
    sourceText:
      "Fogsphere describes retail spill and fallen-item detection with incident clips, plus blocked-aisle monitoring. This supports the operational use case; it is not evidence that this exact workflow runs in our Spark demo or that their deployment uses VSS.",
    source: "https://fogsphere.com/industries-served/retail/",
    sourceLabel: "Fogsphere · Retail safety and operations",
    boundary:
      "Illustrative VSS adaptation. Hazard rules need store-specific validation; alert delivery and cleanup are operator workflows.",
    alt: "Illustrative supermarket walkway with a fallen bottle and visible liquid spill",
  },
  {
    sector: "SMART CITIES",
    name: "Stopped-vehicle incident review",
    place: "Urban intersection · through lane",
    image: "city",
    after: "city",
    icon: IconCar,
    accent: "#a9c8f0",
    question: "Which vehicle remains stopped as traffic moves?",
    observation: "Signal changes. The van remains stopped.",
    action:
      "A traffic operator reviews the camera, incident duration and surrounding traffic before deciding the response.",
    benefit: "Bring a developing disruption into view.",
    pipeline: ["Vehicle tracks", "Duration threshold", "Incident review"],
    sourceTitle: "Documented VSS Smart City workflow",
    sourceText:
      "NVIDIA’s Smart City Blueprint includes vehicle-stalling candidates based on configured low-speed and duration thresholds, with incident retrieval and reporting. These two generated moments illustrate the idea, not a measured duration or a diagnosed breakdown.",
    source:
      "https://docs.nvidia.com/vss/3.2.0/smartcity-docs/Blueprint-deep-dive.html",
    sourceLabel: "NVIDIA VSS · Smart City Blueprint",
    boundary:
      "Requires the smart-city pipeline and configured thresholds. A stop alone does not establish a breakdown.",
    alt: "Illustrative traffic scene with a white van and queued cars at a red signal",
  },
];
export function VssIndustryScene({
  step,
  onJump,
}: {
  step: number;
  onJump: (index: number) => void;
}) {
  const [sources, setSources] = useState(false);
  const [frame, setFrame] = useState<"before" | "after" | null>(null);
  const [lastStep, setLastStep] = useState(step);
  if (lastStep !== step) {
    setLastStep(step);
    setFrame(null);
    setSources(false);
  }
  if (step === 8)
    return (
      <div className={s.ending}>
        <div className={s.endGrid}>
          {cases.map((item, i) => (
            <button key={item.sector} onClick={() => onJump(14 + i * 2)}>
              <img src={`/vision/industry-${item.image}-v2.png`} alt="" />
              <span>
                <small>{item.sector}</small>
                <strong>{item.benefit}</strong>
              </span>
              <IconArrowRight size={19} />
            </button>
          ))}
        </div>
        <div className={s.endQuestion}>
          <span>BRING IT BACK TO YOUR OPERATION</span>
          <h2>What moment would you want your cameras to find?</h2>
          <p>
            Choose a camera, a meaningful event, and the person who needs the
            evidence.
          </p>
        </div>
      </div>
    );
  const index = Math.floor(step / 2),
    result = step % 2 === 1,
    item = cases[index],
    Icon = item.icon;
  const showAfter = Boolean(item.after) && (frame ? frame === "after" : result);
  return (
    <div
      className={s.case}
      data-industry={index}
      data-result={result}
      style={{ "--case-accent": item.accent } as React.CSSProperties}
    >
      <div className={s.visual}>
        <div className={s.photograph}>
          <img
            className={s.basePhoto}
            src={`/vision/industry-${item.image}-v2.png`}
            alt={item.alt}
            aria-hidden={showAfter}
          />
          {item.after && (
            <img
              className={s.afterPhoto}
              data-visible={showAfter}
              src={`/vision/industry-${item.after}-after-v2.png`}
              alt={
                index === 1
                  ? "The same technician placing the inspected part into its carton"
                  : "The same van remains stopped after the signal turns green"
              }
              aria-hidden={!showAfter}
            />
          )}
          <div className={s.photoShade} />
          <div className={s.photoTop}>
            <span>
              <i />
              {item.place}
            </span>
            <small>AI-generated illustration</small>
          </div>
          {result && index === 0 && (
            <>
              <div className={s.personMarker}>
                <span>Pedestrian</span>
              </div>
              <div className={s.forkliftMarker}>
                <span>Forklift</span>
              </div>
            </>
          )}
          {result && index === 2 && (
            <div className={s.spillMarker}>
              <span>Visible spill</span>
            </div>
          )}
          {result && index === 3 && (
            <div className={s.vanMarker}>
              <span>Still stopped · review duration</span>
            </div>
          )}
          <div className={s.photoBottom}>
            <Icon size={22} />
            <span>{item.name}</span>
          </div>
        </div>
        {item.after ? (
          <div
            className={s.frameStrip}
            aria-label="Compare illustrative moments"
          >
            <span>Compare the sequence</span>
            <button
              aria-pressed={!showAfter}
              onClick={() => setFrame("before")}
            >
              <img src={`/vision/industry-${item.image}-v2.png`} alt="" />
              {index === 1 ? "01 · Inspection" : "01 · Signal red"}
            </button>
            <span className={s.sequenceArrow}>→</span>
            <button aria-pressed={showAfter} onClick={() => setFrame("after")}>
              <img src={`/vision/industry-${item.after}-after-v2.png`} alt="" />
              {index === 1 ? "02 · Packing" : "02 · Signal green"}
            </button>
          </div>
        ) : (
          <div className={s.caption}>
            {index === 0
              ? "A proximity signal is a reason to inspect the interaction—not a verdict."
              : "The alert points to a visible condition. Staff decide and carry out the response."}
          </div>
        )}
      </div>
      <div className={s.story}>
        <div className={s.label}>
          <span>{item.sector}</span>
          <small>
            {result ? "EVIDENCE → ACTION" : "THE OPERATIONAL QUESTION"}
          </small>
        </div>
        <h2>“{item.question}”</h2>
        {!result ? (
          <div className={s.setup}>
            <div className={s.pipeline}>
              {item.pipeline.map((label, i) => (
                <React.Fragment key={label}>
                  <span>
                    <b>0{i + 1}</b>
                    {label}
                  </span>
                  {i < 2 && <i>↓</i>}
                </React.Fragment>
              ))}
            </div>
            <p className={s.scrollHint}>
              Scroll to put the evidence to work <IconArrowRight size={15} />
            </p>
          </div>
        ) : (
          <div className={s.result}>
            <small>ILLUSTRATIVE FINDING</small>
            <h3>{item.observation}</h3>
            <div className={s.action}>
              <span>WHAT YOUR TEAM DOES NEXT</span>
              <p>{item.action}</p>
            </div>
            <strong>{item.benefit}</strong>
          </div>
        )}
        <button className={s.researchButton} onClick={() => setSources(true)}>
          Research behind this example <span>↗</span>
        </button>
      </div>
      {sources && (
        <div
          className={s.research}
          role="dialog"
          aria-label="Research behind this example"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              setSources(false);
            }
          }}
        >
          <button
            ref={(button) => button?.focus({ preventScroll: true })}
            onClick={() => setSources(false)}
            aria-label="Close research"
          >
            <IconX size={20} />
          </button>
          <small>REAL-WORLD GROUNDING</small>
          <h3>{item.sourceTitle}</h3>
          <p>{item.sourceText}</p>
          <a href={item.source} target="_blank" rel="noopener noreferrer">
            {item.sourceLabel} ↗
          </a>
          <p className={s.boundary}>{item.boundary}</p>
        </div>
      )}
    </div>
  );
}
