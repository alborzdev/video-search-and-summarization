#!/usr/bin/env node

import crypto from "node:crypto";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  throw new Error("compiled validator module path is required");
}

const validatorModule = await import(pathToFileURL(modulePath).href);
const validate = validatorModule.validateWebSocketMessageWithConversationId;
if (typeof validate !== "function") {
  throw new Error("compiled validator export is absent");
}

const candidate = {
  type: "system_response_message",
  status: "complete",
  content: {},
};
const candidateBytes = Buffer.from(JSON.stringify(candidate));
let rejected = false;
let errorName = null;
let errorMessageSha256 = null;

try {
  validate(candidate);
} catch (error) {
  rejected = true;
  errorName = error?.constructor?.name ?? "UnknownError";
  errorMessageSha256 = crypto
    .createHash("sha256")
    .update(String(error?.message ?? ""))
    .digest("hex");
}

process.stdout.write(
  `${JSON.stringify(
    {
      candidateSha256: crypto.createHash("sha256").update(candidateBytes).digest("hex"),
      errorMessageSha256,
      errorName,
      rejected,
    },
    null,
    2,
  )}\n`,
);

if (!rejected) {
  process.exitCode = 2;
}
