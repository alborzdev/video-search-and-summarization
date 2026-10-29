// SPDX-License-Identifier: MIT

import damageResult from "../../../public/defense-story/v2/damage-box-response.json";
import { LocalVisionLauncher } from "../LocalVisionLauncher";
import s from "./DefenseStory.module.css";
import { defenseBeats as beats, defenseSources } from "./defenseStory";
import {
  IconArrowRight,
  IconCheck,
  IconExternalLink,
  IconCameraOff,
  IconWifiOff,
  IconDrone,
  IconCamera,
  IconTruck,
} from "@tabler/icons-react";
import React, { useEffect, useState } from "react";

const asset = (name: string) => `/defense-story/v2/${name}`;
const captureSelector =
  '[data-testid="defense-story"] [data-local-vision-source]';
const places = [
  {
    name: "Airfield recovery",
    short: "DRONE SURVEY",
    x: 575,
    y: 420,
    index: 1,
    icon: IconDrone,
    image: "damage-input.jpg",
    alt: "Drone view of damaged airfield pavement",
    source: "Drone camera · pavement survey",
    output: "Damage finding",
    location: "At the ground station",
  },
  {
    name: "Site watch",
    short: "HANGAR GATE",
    x: 1065,
    y: 535,
    index: 3,
    icon: IconCamera,
    image: "site.png",
    alt: "Hangar gate with a person near the marked boundary",
    source: "Cam 01 · hangar gate",
    output: "Entry for review",
    location: "On the local site network",
  },
  {
    name: "Vehicle visibility",
    short: "SERVICE VEHICLE",
    x: 515,
    y: 575,
    index: 5,
    icon: IconTruck,
    image: "vehicle.png",
    alt: "Rear camera with a person behind the vehicle",
    source: "Rear vehicle camera",
    output: "Rear-view cue",
    location: "Inside the vehicle",
  },
] as const;
function SourceNote({ index }: { index: number }) {
  const source = defenseSources[index];
  return (
    <details className={s.sourceNote}>
      <summary>
        Why this mission <IconExternalLink size={12} />
      </summary>
      <div>
        <small>{source.name}</small>
        <strong>{source.title}</strong>
        <p>{source.text}</p>
        <a href={source.url} target="_blank" rel="noreferrer">
          Read the primary source <IconArrowRight size={12} />
        </a>
      </div>
    </details>
  );
}
function PersonOverlay({ vehicle }: { vehicle: boolean }) {
  return (
    <svg
      className={s.overlay}
      viewBox="0 0 1672 941"
      aria-label={
        vehicle
          ? "Illustrative person cue behind the vehicle"
          : "Illustrative person cue and hangar boundary"
      }
    >
      {!vehicle && (
        <>
          <path
            className={s.zone}
            d="M 1040 560 L 1510 600 L 1660 910 L 860 910 Z"
          />
          <text x="1020" y="867">
            HANGAR BOUNDARY
          </text>
        </>
      )}
      <rect
        x={vehicle ? 465 : 1240}
        y={vehicle ? 319 : 505}
        width={vehicle ? 131 : 99}
        height={vehicle ? 257 : 253}
        rx="3"
      />
      <text x={vehicle ? 465 : 1240} y={vehicle ? 295 : 481}>
        PERSON
      </text>
    </svg>
  );
}
export function DefenseDiorama({
  active,
  go,
  pause,
  onOpenDemo,
}: {
  active: number;
  go: (index: number) => void;
  pause: () => void;
  onOpenDemo: () => void;
}) {
  const [layers, setLayers] = useState(true),
    [maskMode, setMaskMode] = useState("Mask"),
    [cameraLost, setCameraLost] = useState(false),
    [uplink, setUplink] = useState(true),
    [selected, setSelected] = useState(0);
  useEffect(() => {
    setLayers(true);
    setMaskMode("Mask");
    setCameraLost(false);
    setUplink(true);
  }, [active]);
  const mi = active >= 7 ? selected : active < 3 ? 0 : active < 5 ? 1 : 2;
  const place = places[mi],
    beat = beats[active],
    feed = active > 0 && active < 7,
    close = feed && active % 2 === 0;
  const action = (fn: () => void) => {
    pause();
    fn();
  };
  return (
    <section className={s.spatialStory} data-spatial-step={active}>
      <div className={s.spatialVisual}>
        <div className={s.worldLabel}>
          <span>THE SAME AIRFIELD</span>
          <span>Illustrated setting · conceptual locations</span>
        </div>
        <svg
          className={s.world}
          viewBox="0 0 1672 941"
          role="img"
          aria-label="Persistent airfield diorama with drone survey, hangar gate and service vehicle"
          data-testid="defense-diorama"
        >
          <g className={s.worldFraming}>
            <image
              href={asset("airfield-diorama.png")}
              width="1672"
              height="941"
              data-testid="defense-diorama-image"
            />
            <g
              className={s.worldSight}
              data-visible={active === 1 || active === 2}
              aria-hidden="true"
            >
              <path d="M463 173 450 396 665 470Z" />
              <path d="M463 173 575 420" className={s.sightLine} />
            </g>
            <g
              className={s.worldSight}
              data-visible={active === 3 || active === 4}
              aria-hidden="true"
            >
              <path d="M1070 446 955 563 1150 635Z" />
              <path d="M1070 446 1065 535" className={s.sightLine} />
            </g>
            <g
              className={s.worldSight}
              data-visible={active === 5 || active === 6}
              aria-hidden="true"
            >
              <path d="M485 576 338 566 391 683Z" />
              <path d="M485 576 390 620" className={s.sightLine} />
            </g>
            <g
              className={s.worldNetwork}
              data-visible={active >= 7}
              aria-hidden="true"
            >
              <path d="M575 420 Q480 300 650 270 M1065 535 Q1190 560 1210 475 M390 620 Q430 650 515 575" />
              <circle cx="650" cy="270" r="15" />
              <circle cx="1210" cy="475" r="15" />
              <circle cx="515" cy="575" r="15" />
              <text x="675" y="275">
                GROUND STATION
              </text>
              <text x="1235" y="480">
                SITE NETWORK
              </text>
            </g>
            {places.map((p, i) => (
              <g
                key={p.name}
                className={s.worldPin}
                data-selected={active === 0 || i === mi || active >= 7}
                transform={`translate(${p.x},${p.y})`}
              >
                <circle className={s.pinHalo} r="22" />
                <circle r="11" />
                <path d="M0 -22 V-57 H132" />
                <rect x="10" y="-85" width="189" height="30" rx="4" />
                <text x="21" y="-64">
                  0{i + 1} / {p.short}
                </text>
              </g>
            ))}
          </g>
        </svg>
        <div
          className={s.cameraPortal}
          data-open={feed}
          data-expanded={close}
          aria-hidden={!feed}
        >
          {feed && (
            <>
              <div className={s.portalHeader}>
                <span>
                  <place.icon size={14} />0{mi + 1} / {place.source}
                </span>
                <div>
                  {active === 2 ? (
                    ["Image", "Box", "Mask"].map((mode) => (
                      <button
                        key={mode}
                        aria-pressed={maskMode === mode}
                        onClick={() => action(() => setMaskMode(mode))}
                      >
                        {mode}
                      </button>
                    ))
                  ) : mi > 0 ? (
                    <button
                      aria-pressed={layers}
                      onClick={() => action(() => setLayers(!layers))}
                    >
                      {layers ? "Camera only" : "Show AI cue"}
                    </button>
                  ) : null}
                </div>
              </div>
              <div className={s.portalImage}>
                {cameraLost ? (
                  <div className={s.unavailable} role="status">
                    <IconCameraOff size={36} />
                    <h2>Rear camera unavailable</h2>
                    <p>Coverage unknown. Check the camera link.</p>
                  </div>
                ) : (
                  <>
                    <img
                      src={asset(place.image)}
                      alt={place.alt}
                      data-local-vision-source={`Illustration · ${place.name}`}
                    />
                    {mi > 0 && layers && <PersonOverlay vehicle={mi === 2} />}
                    {active === 2 && maskMode === "Mask" && (
                      <img
                        className={s.mask}
                        src={asset("damage-mask.png")}
                        alt="Recorded SAM mask of the pavement depression"
                      />
                    )}
                    {active === 2 && maskMode === "Box" && (
                      <svg
                        className={s.overlay}
                        viewBox="0 0 1024 576"
                        aria-label="Recorded Moondream pothole box"
                      >
                        <rect
                          x="377"
                          y="137.25"
                          width="342"
                          height="315"
                          rx="3"
                        />
                      </svg>
                    )}
                    <span className={s.imageBadge}>
                      {active === 2
                        ? "RECORDED LOCAL MASK / ILLUSTRATED INPUT"
                        : "ILLUSTRATED CAMERA VIEW"}
                    </span>
                  </>
                )}
              </div>
              <div className={s.portalFooter}>
                <span>
                  {close ? "02 / REVIEW THE RESULT" : "01 / FOLLOW THIS CAMERA"}
                </span>
                {active === 6 ? (
                  <button
                    aria-pressed={cameraLost}
                    onClick={() => action(() => setCameraLost(!cameraLost))}
                  >
                    {cameraLost
                      ? "Restore camera example"
                      : "Simulate camera loss"}
                  </button>
                ) : (
                  <span>
                    {mi === 0
                      ? "Engineer review"
                      : mi === 1
                      ? "Security review"
                      : "Driver attention"}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
        <div
          className={s.worldCompute}
          data-visible={active >= 7}
          aria-hidden={active < 7}
        >
          {active >= 7 && (
            <>
              <img
                src="/vision/anvil-t5.png"
                alt="Anvil-T5 deployment target"
              />
              <div>
                <small>CONNECT TECH / JETSON THOR</small>
                <h2>
                  {active === 8 ? place.location : "Process here. Review here."}
                </h2>
                <p>
                  {active === 8
                    ? place.output
                    : "Keep local results with the operator."}
                </p>
              </div>
            </>
          )}
        </div>
        <div
          className={s.storyTrail}
          aria-label="Findings carried through the story"
        >
          {places.map((p, i) => (
            <button
              key={p.name}
              data-reached={active >= p.index + 1}
              data-current={feed && mi === i}
              onClick={() => go(p.index)}
            >
              <span>
                {active >= p.index + 1 ? (
                  <IconCheck size={12} />
                ) : (
                  String(i + 1).padStart(2, "0")
                )}
              </span>
              {active >= p.index + 1 ? p.output : p.name}
            </button>
          ))}
        </div>
      </div>
      <aside className={s.spatialCopy}>
        <div className={s.spatialHeading} key={active}>
          <span className={s.eyebrow}>{beat.label}</span>
          <h1>{beat.title}</h1>
          <p>{beat.body}</p>
        </div>
        <div className={s.spatialResult}>
          <small>
            {active === 0
              ? "THE TOUR"
              : active >= 7
              ? "THE LOCAL SYSTEM"
              : "WHAT THIS ADDS"}
          </small>
          <h2>{cameraLost ? "Camera link lost" : beat.outcome}</h2>
          {active === 0 && (
            <>
              <p>
                Start with the drone. Carry its finding forward. Then follow the
                gate and vehicle cameras.
              </p>
              <button className={s.primary} onClick={() => go(1)}>
                Follow the drone <IconArrowRight size={16} />
              </button>
            </>
          )}
          {active === 1 && (
            <p>
              The highlighted area connects the drone to its inspection view.
              Next, examine the same image.
            </p>
          )}
          {active === 2 && (
            <>
              <p className={s.modelReceipt}>
                Moondream 2 → SAM 2.1 Tiny ·{" "}
                {Math.round(damageResult.timings_ms.total)} ms
              </p>
              <div className={s.tryModel} onClick={pause}>
                <LocalVisionLauncher captureSelector={captureSelector} />
                <small>
                  Spark · one recorded warm request. Try “pothole” with box
                  guidance.
                </small>
              </div>
            </>
          )}
          {active === 3 && (
            <p>
              The drone finding stays in the trail below. The next camera
              watches the hangar entrance.
            </p>
          )}
          {active === 4 && (
            <dl className={s.resultFacts}>
              <div>
                <dt>SOURCE / EXAMPLE EVENT TIME</dt>
                <dd>Cam 01 · 14:32:08 (authored)</dd>
              </div>
              <div>
                <dt>REVIEW</dt>
                <dd>Access permission not established.</dd>
              </div>
            </dl>
          )}
          {active === 5 && (
            <p>
              Follow the service road to the truck. Its rear camera reveals a
              view the driver needs.
            </p>
          )}
          {active === 6 && (
            <p>
              {cameraLost
                ? "Missing coverage is shown explicitly. Restore the example to review the person."
                : "The person stays in the same rear view. The driver remains in control."}
            </p>
          )}
          {active === 7 && (
            <>
              <div className={s.localStates}>
                <span>
                  <IconCheck size={13} />
                  Local processing
                </span>
                <span>
                  <IconCheck size={13} />
                  Operator review
                </span>
              </div>
              <button
                className={s.linkToggle}
                aria-pressed={!uplink}
                onClick={() => action(() => setUplink(!uplink))}
              >
                <IconWifiOff size={16} />
                {uplink ? "Simulate uplink loss" : "Restore simulated link"}
              </button>
              <p role="status">
                {uplink
                  ? "Remote sharing: available"
                  : "Remote sharing: queued (illustration)"}
              </p>
            </>
          )}
          {active === 8 && (
            <>
              <div className={s.deploymentChoices}>
                {places.map((p, i) => (
                  <button
                    key={p.name}
                    aria-pressed={selected === i}
                    onClick={() => action(() => setSelected(i))}
                  >
                    <p.icon size={16} />
                    {p.name}
                    <IconArrowRight size={14} />
                  </button>
                ))}
              </div>
              <button className={s.primary} onClick={onOpenDemo}>
                Open the defense demos <IconArrowRight size={15} />
              </button>
            </>
          )}
        </div>
        {active > 0 && (
          <SourceNote index={active >= 7 ? (active === 7 ? 3 : 4) : mi} />
        )}
      </aside>
    </section>
  );
}
