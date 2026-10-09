/** @jest-environment node */

import { historyRequest } from "../../../server/vision/historyRequest";
import { createServer } from "node:http";

describe("history transport deadlines", () => {
  it("waits for delayed headers but still enforces the total deadline", async () => {
    const server = createServer((request, response) => {
      request.resume();
      const timer = setTimeout(() => response.end('{"ready":true}'), 80);
      response.on("close", () => clearTimeout(timer));
    });
    await new Promise<void>((resolve) =>
      server.listen(0, "127.0.0.1", resolve)
    );
    const address = server.address() as { port: number };
    try {
      const url = `http://127.0.0.1:${address.port}`;
      const response = await historyRequest(
        url,
        { method: "POST", body: "{}" },
        1000
      );
      expect(response.status).toBe(200);
      expect(JSON.parse(await response.text())).toEqual({ ready: true });
      await expect(
        historyRequest(url, { method: "POST", body: "{}" }, 10)
      ).rejects.toThrow("deadline");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("rejects an oversized local response", async () => {
    const server = createServer((_request, response) => {
      response.end(Buffer.alloc(4 * 1024 * 1024 + 1));
    });
    await new Promise<void>((resolve) =>
      server.listen(0, "127.0.0.1", resolve)
    );
    const address = server.address() as { port: number };
    try {
      await expect(
        historyRequest(`http://127.0.0.1:${address.port}`, {}, 1000)
      ).rejects.toThrow("size limit");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});
