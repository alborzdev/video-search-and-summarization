// SPDX-License-Identifier: MIT

import type {
  InvestigationCreateRequest,
  InvestigationEvidence,
  InvestigationRecord,
} from "../../../components/vision-intelligence/investigation";
import type { NextApiRequest, NextApiResponse } from "next";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";

const STORE_DIR =
  process.env.VISION_INVESTIGATIONS_DIR ||
  "/tmp/vss-vision-intelligence-investigations";
const ID_PATTERN = /^[a-f0-9-]{36}$/;
const EVIDENCE_KEY_PATTERN = /^[a-f0-9]{64}$/;
const EVIDENCE_CLIP_API_URL = (
  process.env.EVIDENCE_CLIP_API_URL || "http://127.0.0.1:8098"
).replace(/\/$/, "");

function single(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] || "" : value || "";
}

function text(value: unknown, maxLength: number): string {
  return typeof value === "string" ? value.trim().slice(0, maxLength) : "";
}

function validTime(value: string): boolean {
  return Boolean(value) && Number.isFinite(Date.parse(value));
}

function validateEvidence(value: unknown): InvestigationEvidence[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 6) {
    throw new Error("An investigation requires one to six evidence clips.");
  }
  return value.map((item) => {
    if (!item || typeof item !== "object") {
      throw new Error("One of the evidence clips is invalid.");
    }
    const candidate = item as Partial<InvestigationEvidence>;
    const startTime = text(candidate.start_time, 80);
    const endTime = text(candidate.end_time, 80);
    if (
      !text(candidate.client_id, 512) ||
      !text(candidate.sensor_id, 160) ||
      !text(candidate.source_name, 256) ||
      !validTime(startTime) ||
      !validTime(endTime) ||
      Date.parse(endTime) <= Date.parse(startTime)
    ) {
      throw new Error(
        "One of the evidence clips has invalid source or time data."
      );
    }
    return {
      client_id: text(candidate.client_id, 512),
      end_time: endTime,
      image_url: text(candidate.image_url, 2_000),
      match_type: text(candidate.match_type, 200),
      sensor_id: text(candidate.sensor_id, 160),
      source_name: text(candidate.source_name, 256),
      start_time: startTime,
      title: text(candidate.title, 500) || "Video evidence",
    };
  });
}

async function retainEvidence(
  item: InvestigationEvidence
): Promise<InvestigationEvidence> {
  try {
    const response = await fetch(`${EVIDENCE_CLIP_API_URL}/prepare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sensorId: item.sensor_id,
        startTime: item.start_time,
        endTime: item.end_time,
      }),
      signal: AbortSignal.timeout(320_000),
    });
    const payload = (await response.json().catch(() => null)) as {
      key?: string;
    } | null;
    if (response.ok && payload?.key && EVIDENCE_KEY_PATTERN.test(payload.key)) {
      return {
        ...item,
        media_status: "retained",
        video_url: `/api/vision/evidence-media?key=${encodeURIComponent(
          payload.key
        )}`,
      };
    }
  } catch {
    // The report still retains its timestamps and analysis when source media
    // has already moved outside VST's rolling retention window.
  }
  return { ...item, media_status: "source_retention" };
}

function validateRequest(value: unknown): InvestigationCreateRequest {
  if (!value || typeof value !== "object") {
    throw new Error("A valid investigation is required.");
  }
  const request = value as Partial<InvestigationCreateRequest>;
  const title = text(request.title, 500);
  const query = text(request.query, 1_000);
  const severity = request.severity;
  const disposition = request.disposition;
  if (
    !title ||
    !query ||
    !request.analysis ||
    typeof request.analysis !== "object"
  ) {
    throw new Error(
      "The investigation title, query, and analysis are required."
    );
  }
  if (
    severity !== "critical" &&
    severity !== "high" &&
    severity !== "medium" &&
    severity !== "low"
  ) {
    throw new Error("The investigation severity is invalid.");
  }
  if (
    disposition !== "dismissed" &&
    disposition !== "open" &&
    disposition !== "resolved" &&
    disposition !== "under_review"
  ) {
    throw new Error("The investigation disposition is invalid.");
  }
  return {
    analysis: request.analysis,
    disposition,
    evidence: validateEvidence(request.evidence),
    notes: text(request.notes, 5_000),
    query,
    severity,
    title,
  };
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function reportHtml(record: InvestigationRecord): string {
  const evidence = new Map(
    record.analysis.evidence.map((item) => [item.evidence_id, item])
  );
  const claim = (value: { evidence_ids: string[]; text: string }) =>
    `<li><span>${escapeHtml(value.text)}</span><small>${value.evidence_ids
      .map((id) => `<a href="#${escapeHtml(id)}">${escapeHtml(id)}</a>`)
      .join(" ")}</small></li>`;
  const evidenceCards = record.evidence
    .map((item, index) => {
      const evidenceId = `E${index + 1}`;
      const inspected = evidence.get(evidenceId);
      const params = new URLSearchParams({
        sensorId: item.sensor_id,
        startTime: item.start_time,
        endTime: item.end_time,
      });
      const retainedVideo =
        item.media_status === "retained" && item.video_url
          ? item.video_url
          : "";
      return `<article id="${evidenceId}">
        <div class="evidence-media">
          ${
            retainedVideo
              ? `<video preload="metadata" muted playsinline src="${escapeHtml(
                  retainedVideo
                )}"></video>`
              : item.image_url
              ? `<img src="${escapeHtml(item.image_url)}" alt="" />`
              : ""
          }
          ${retainedVideo ? "" : "<video controls hidden></video>"}
        </div>
        <div><b>${evidenceId} · ${escapeHtml(item.title)}</b><span>${escapeHtml(
        item.source_name
      )} · <time data-local-time="${escapeHtml(item.start_time)}">${escapeHtml(
        item.start_time
      )}</time></span>
        <p>${escapeHtml(
          inspected?.observation || "Evidence retained for review."
        )}</p>
        <small class="retention">${
          retainedVideo
            ? "Media retained locally on Thor"
            : "Playback follows the source retention window"
        }</small>
        <button data-evidence="/api/vision/evidence?${escapeHtml(
          params.toString()
        )}" data-retained="${escapeHtml(
          retainedVideo
        )}" onclick="playEvidence(this)">Play exact clip</button></div>
      </article>`;
    })
    .join("");
  return `<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width"/>
  <title>${escapeHtml(record.title)} · Vision Intelligence</title><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%23050a0c'/%3E%3Cpath d='M16 32h32M32 16v32' stroke='%2318c5cd' stroke-width='6' stroke-linecap='round'/%3E%3C/svg%3E"/><style>
  :root{color-scheme:light;font-family:Aesthetica,"Manrope Variable",Manrope,system-ui,sans-serif;background:#f7f7f4;color:#173335}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 82% 0,rgba(20,154,154,.08),transparent 30%),#f7f7f4}main{width:min(1120px,calc(100% - 40px));margin:40px auto 80px}.brand{color:#0f7f80;font-size:11px;font-weight:700;letter-spacing:.13em;text-transform:uppercase}h1{max-width:850px;margin:14px 0 10px;font-size:36px;line-height:1.12;letter-spacing:-.025em}.meta{display:flex;gap:8px;flex-wrap:wrap}.meta span{padding:6px 9px;border:1px solid #d5dfdc;border-radius:999px;color:#637574;background:#fff;font-size:11px}.summary,.section{margin-top:24px;padding:24px;border:1px solid #d8e1de;border-radius:12px;background:rgba(255,255,255,.86);box-shadow:0 12px 34px rgba(24,55,55,.04)}.summary p{font-size:18px;line-height:1.55}.columns{display:grid;grid-template-columns:1fr 1fr;gap:16px}.section h2{margin:0 0 16px;font-size:15px;color:#0f7f80}.section ul{display:grid;gap:11px;margin:0;padding:0;list-style:none}.section li{display:flex;gap:12px;justify-content:space-between;color:#355052;font-size:13px;line-height:1.5}.section small{white-space:nowrap}.section a{color:#176f92;text-decoration:none}.evidence{display:grid;gap:10px;margin-top:24px}.evidence article{display:grid;grid-template-columns:280px 1fr;gap:18px;min-height:165px;overflow:hidden;border:1px solid #d8e1de;border-radius:12px;background:#fff;box-shadow:0 12px 34px rgba(24,55,55,.04)}.evidence-media{background:#123033}.evidence img,.evidence video{width:100%;height:100%;min-height:165px;object-fit:cover}.evidence article>div:last-child{padding:20px 20px 16px 0}.evidence b,.evidence span{display:block}.evidence span{margin-top:5px;color:#728180;font-size:11px}.evidence p{color:#435b5c;font-size:12px;line-height:1.55}.evidence .retention{display:block;margin:0 0 10px;color:#0f7f80}.evidence button{padding:8px 11px;border:1px solid #149a9a;border-radius:6px;background:#f0f9f7;color:#0f7475;cursor:pointer}.notes{white-space:pre-wrap;color:#435b5c;line-height:1.6}@media(max-width:700px){.columns{grid-template-columns:1fr}.evidence article{grid-template-columns:1fr}.evidence article>div:last-child{padding:16px}.evidence-media{max-height:260px}}
  </style></head><body><main><div class="brand">Vision Intelligence · Local NVIDIA Thor</div><h1>${escapeHtml(
    record.title
  )}</h1><div class="meta"><span>${escapeHtml(
    record.severity
  )} severity</span><span>${escapeHtml(
    record.disposition.replaceAll("_", " ")
  )}</span><span><time data-local-time="${escapeHtml(
    record.created_at
  )}">${escapeHtml(record.created_at)}</time></span><span>${escapeHtml(
    record.id
  )}</span></div><section class="summary"><div class="brand">Evidence briefing</div><p>${escapeHtml(
    record.analysis.summary
  )}</p></section><div class="columns"><section class="section"><h2>Observed facts</h2><ul>${record.analysis.observations
    .map(claim)
    .join(
      ""
    )}</ul></section><section class="section"><h2>AI interpretation</h2><ul>${
    record.analysis.interpretations.map(claim).join("") ||
    "<li>No separate interpretation was recorded.</li>"
  }</ul></section></div>${
    record.notes
      ? `<section class="section"><h2>Operator notes</h2><div class="notes">${escapeHtml(
          record.notes
        )}</div></section>`
      : ""
  }<section class="evidence">${evidenceCards}</section></main><script>
  async function playEvidence(button){button.disabled=true;button.textContent='Preparing exact clip…';try{let videoUrl=button.dataset.retained;if(!videoUrl){const response=await fetch(button.dataset.evidence);const data=await response.json();if(!response.ok||!data.videoUrl)throw new Error(data.error||'Clip unavailable');videoUrl=data.videoUrl}const article=button.closest('article');const video=article.querySelector('video');article.querySelector('img')?.setAttribute('hidden','');if(video.src!==new URL(videoUrl,location.href).href)video.src=videoUrl;video.hidden=false;video.muted=false;video.controls=true;await video.play();button.textContent='Playing exact clip'}catch(error){button.disabled=false;button.textContent=error.message||'Clip unavailable'}}
  document.querySelectorAll('[data-local-time]').forEach(function(element){var value=element.getAttribute('data-local-time');var date=new Date(value);if(!Number.isNaN(date.getTime()))element.textContent=date.toLocaleString()});
  </script></body></html>`;
}

async function readRecord(id: string): Promise<InvestigationRecord> {
  return JSON.parse(
    await readFile(path.join(STORE_DIR, `${id}.json`), "utf8")
  ) as InvestigationRecord;
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  await mkdir(STORE_DIR, { recursive: true });
  if (req.method === "POST") {
    try {
      const request = validateRequest(req.body);
      const retainedEvidence: InvestigationEvidence[] = [];
      for (const item of request.evidence) {
        retainedEvidence.push(await retainEvidence(item));
      }
      const id = randomUUID();
      const record: InvestigationRecord = {
        ...request,
        evidence: retainedEvidence,
        created_at: new Date().toISOString(),
        id,
        report_url: `/api/vision/investigations?id=${encodeURIComponent(
          id
        )}&format=html`,
      };
      const temporary = path.join(STORE_DIR, `.${id}.tmp`);
      await writeFile(temporary, JSON.stringify(record, null, 2), {
        encoding: "utf8",
        flag: "wx",
      });
      await rename(temporary, path.join(STORE_DIR, `${id}.json`));
      res.setHeader("Cache-Control", "no-store");
      return res.status(201).json(record);
    } catch (error) {
      return res.status(400).json({
        error:
          error instanceof Error
            ? error.message
            : "The investigation could not be created.",
      });
    }
  }

  if (req.method === "GET") {
    const id = single(req.query.id);
    try {
      if (id) {
        if (!ID_PATTERN.test(id)) {
          return res.status(422).json({ error: "Invalid investigation ID." });
        }
        const record = await readRecord(id);
        if (single(req.query.format) === "html") {
          res.setHeader("Content-Type", "text/html; charset=utf-8");
          res.setHeader("Cache-Control", "private, no-store");
          if (single(req.query.download) === "true") {
            res.setHeader(
              "Content-Disposition",
              `attachment; filename="vision-investigation-${id}.html"`
            );
          }
          return res.status(200).send(reportHtml(record));
        }
        return res.status(200).json(record);
      }
      const files = (await readdir(STORE_DIR))
        .filter((file) => ID_PATTERN.test(file.replace(/\.json$/, "")))
        .slice(-100);
      const records = await Promise.all(
        files.map((file) => readRecord(file.replace(/\.json$/, "")))
      );
      return res.status(200).json({
        investigations: records.sort((left, right) =>
          right.created_at.localeCompare(left.created_at)
        ),
      });
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      return res.status(code === "ENOENT" ? 404 : 500).json({
        error:
          code === "ENOENT"
            ? "Investigation not found."
            : "Investigations are unavailable.",
      });
    }
  }

  res.setHeader("Allow", "GET, POST");
  return res.status(405).json({ error: "Method not allowed." });
}
