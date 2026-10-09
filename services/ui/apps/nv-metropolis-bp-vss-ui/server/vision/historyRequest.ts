// SPDX-License-Identifier: MIT
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";

/** Local history builds need their full deadline, including response headers.
 * Node fetch's separate five-minute header deadline can expire first.
 */
export function historyRequest(
  url: string,
  init: RequestInit,
  timeoutMs: number
) {
  return new Promise<{ ok: boolean; status: number; text(): Promise<string> }>(
    (resolve, reject) => {
      const target = new URL(url);
      if (!["http:", "https:"].includes(target.protocol)) {
        reject(new Error("Unsupported history service protocol."));
        return;
      }
      const headers = Object.fromEntries(new Headers(init.headers).entries());
      const body = init.body;
      if (body != null && typeof body !== "string") {
        reject(new Error("History requests require a JSON string."));
        return;
      }
      if (body != null)
        headers["content-length"] = String(Buffer.byteLength(body));
      const request = (
        target.protocol === "https:" ? httpsRequest : httpRequest
      )(target, { method: init.method || "GET", headers }, (response) => {
        const chunks: Buffer[] = [];
        let bytes = 0;
        response.on("data", (chunk: Buffer) => {
          bytes += chunk.length;
          if (bytes > 4 * 1024 * 1024) {
            request.destroy(
              new Error("History response exceeds the size limit.")
            );
            response.destroy();
          } else chunks.push(chunk);
        });
        response.on("error", reject);
        response.on("end", () => {
          const status = response.statusCode || 502;
          resolve({
            ok: status >= 200 && status < 300,
            status,
            text: async () => Buffer.concat(chunks).toString("utf8"),
          });
        });
      });
      const timer = setTimeout(
        () =>
          request.destroy(
            new Error("Local video history exceeded its request deadline.")
          ),
        timeoutMs
      );
      request.on("error", reject);
      request.on("close", () => clearTimeout(timer));
      request.end(body);
    }
  );
}
