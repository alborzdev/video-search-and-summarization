// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from "next";

const ALLOWED_PICTURE_PATH =
  /\/v1\/(?:live|replay|storage)\/stream\/[^/]+\/picture$/;

function unavailablePicture(
  title = "Preview no longer retained",
  detail = "This source snapshot is outside its rolling recording window."
): Buffer {
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
    <rect width="1280" height="720" fill="#123033"/>
    <circle cx="640" cy="315" r="56" fill="none" stroke="#72c4c1" stroke-width="8"/>
    <path d="M616 295h48v40h-48z M664 305l30-17v54l-30-17z" fill="none" stroke="#72c4c1" stroke-width="8" stroke-linejoin="round"/>
    <text x="640" y="420" text-anchor="middle" fill="#eaf4f2" font-family="system-ui,sans-serif" font-size="34" font-weight="600">${title}</text>
    <text x="640" y="466" text-anchor="middle" fill="#a8c8c5" font-family="system-ui,sans-serif" font-size="23">${detail}</text>
  </svg>`);
}

function sendUnavailable(
  res: NextApiResponse,
  reason: string,
  temporary = false
) {
  res.setHeader("Content-Type", "image/svg+xml; charset=utf-8");
  res.setHeader("Cache-Control", "private, max-age=30");
  res.setHeader("X-Vision-Image-Fallback", reason);
  return res.status(200).send(
    temporary
      ? unavailablePicture(
          "Preview temporarily unavailable",
          "The source is still connected. Try this preview again shortly."
        )
      : unavailablePicture()
  );
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Method not allowed." });
  }

  const requestedPath = Array.isArray(req.query.path)
    ? req.query.path[0]
    : req.query.path;
  if (!requestedPath)
    return res.status(400).json({ error: "Picture path is required." });

  let target: URL;
  try {
    const configuredVst =
      process.env.VST_IMAGE_PROXY_BASE_URL ||
      process.env.NEXT_PUBLIC_VST_API_URL ||
      "http://127.0.0.1:7777/vst/api";
    const configuredUrl = new URL(configuredVst);
    const requestedUrl = new URL(requestedPath, configuredUrl.origin);
    if (
      requestedUrl.origin !== configuredUrl.origin ||
      !ALLOWED_PICTURE_PATH.test(requestedUrl.pathname)
    ) {
      return res.status(400).json({ error: "Unsupported picture path." });
    }
    target = requestedUrl;
  } catch {
    return res.status(400).json({ error: "Invalid picture path." });
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    let upstream = await fetch(target, {
      cache: "no-store",
      signal: controller.signal,
    });

    // VST's replay picture endpoint can reject parallel snapshot requests even
    // when the same recording is available through storage. Reports render
    // several citations at once, so transparently fall back to the equivalent
    // storage snapshot instead of leaving broken evidence images in the page.
    if (!upstream.ok && target.pathname.includes("/v1/replay/stream/")) {
      const storageTarget = new URL(target);
      storageTarget.pathname = storageTarget.pathname.replace(
        "/v1/replay/stream/",
        "/v1/storage/stream/"
      );
      if (!storageTarget.searchParams.has("width")) {
        storageTarget.searchParams.set("width", "1280");
      }
      if (!storageTarget.searchParams.has("height")) {
        storageTarget.searchParams.set("height", "720");
      }
      upstream = await fetch(storageTarget, {
        cache: "no-store",
        signal: controller.signal,
      });
    }

    if (!upstream.ok) {
      return sendUnavailable(
        res,
        String(upstream.status),
        target.pathname.includes("/v1/live/stream/")
      );
    }
    const contentType = upstream.headers.get("content-type") ?? "";
    if (!contentType.startsWith("image/")) {
      return sendUnavailable(res, "unexpected-content", true);
    }
    const image = Buffer.from(await upstream.arrayBuffer());
    res.setHeader("Content-Type", contentType);
    res.setHeader(
      "Cache-Control",
      "public, max-age=60, stale-while-revalidate=300"
    );
    return res.status(200).send(image);
  } catch (error) {
    const reason =
      error instanceof Error && error.name === "AbortError"
        ? "timeout"
        : "unavailable";
    return sendUnavailable(res, reason, true);
  } finally {
    clearTimeout(timeout);
  }
}
