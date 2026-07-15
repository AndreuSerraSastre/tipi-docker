#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

import { unsafeSelfMutationReason } from "./host-exec-safety.mjs";

const args = process.argv.slice(2);
let timeoutSeconds = 300;
let cwd = "";
const commandParts = [];
for (let index = 0; index < args.length; index += 1) {
  if (args[index] === "--timeout") {
    timeoutSeconds = Number(args[++index]);
  } else if (args[index] === "--cwd") {
    cwd = args[++index] ?? "";
  } else if (args[index] !== "--" || commandParts.length > 0) {
    commandParts.push(args[index]);
  }
}
const command = commandParts.join(" ").trim();
if (!command) {
  console.error("Uso: host-exec.mjs [--timeout 300] [--cwd ruta] -- comando");
  process.exit(2);
}
if (!Number.isFinite(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 3600) {
  console.error("El timeout debe estar entre 1 y 3600 segundos.");
  process.exit(2);
}

const safetyReason = unsafeSelfMutationReason(command);
if (safetyReason) {
  console.error(`Operaci\u00f3n bloqueada: ${safetyReason}.`);
  console.error(
    "Para recuperar todo Tipi usa systemctl restart --no-block tipi.service; " +
      "para la voz act\u00faa solo sobre tipi-voice y usa --no-deps al arrancarla.",
  );
  process.exit(126);
}

const projectRoot = process.env.TIPI_PROJECT_ROOT || "/tipi-project";
const isLinuxHost = fs.existsSync("/host/etc/os-release") && fs.existsSync("/proc/1/ns/mnt");

if (isLinuxHost) {
  let hostProjectRoot = process.env.TIPI_HOST_PROJECT_DIR || "";
  if (!hostProjectRoot && process.env.HOSTNAME) {
    const inspect = spawnSync(
      "docker",
      ["inspect", process.env.HOSTNAME, "--format", "{{range .Mounts}}{{if eq .Destination \"/tipi-project\"}}{{.Source}}{{end}}{{end}}"],
      { encoding: "utf8" },
    );
    if (inspect.status === 0) hostProjectRoot = inspect.stdout.trim();
  }
  const hostCwd = cwd || hostProjectRoot || "/";
  const wrapped = `cd -- ${JSON.stringify(hostCwd)} && ${command}`;
  const result = spawnSync(
    "nsenter",
    ["-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "/bin/bash", "-lc", wrapped],
    { encoding: "utf8", timeout: timeoutSeconds * 1000, maxBuffer: 16 * 1024 * 1024 },
  );
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.error?.code === "ETIMEDOUT") {
    console.error(`Comando del host agotado tras ${timeoutSeconds}s.`);
    process.exit(124);
  }
  process.exit(result.status ?? 1);
}

const bridgeRoot = path.join(projectRoot, "data", "host-bridge");
const requests = path.join(bridgeRoot, "requests");
const responses = path.join(bridgeRoot, "responses");
const readyPath = path.join(bridgeRoot, "ready.json");
if (!fs.existsSync(readyPath)) {
  console.error("El puente completo de Windows no esta activo.");
  process.exit(125);
}
fs.mkdirSync(requests, { recursive: true });
fs.mkdirSync(responses, { recursive: true });
const id = `${Date.now()}-${process.pid}-${crypto.randomBytes(6).toString("hex")}`;
const windowsCommand = `$ProgressPreference='SilentlyContinue'; $PSNativeCommandUseErrorActionPreference=$false; ${command}`;
const encodedCommand = Buffer.from(windowsCommand, "utf16le").toString("base64");
const request = {
  id,
  encodedCommand,
  cwd,
  timeoutSeconds,
  requestedAt: new Date().toISOString(),
};
const temporary = path.join(requests, `${id}.tmp`);
const requestPath = path.join(requests, `${id}.json`);
const responsePath = path.join(responses, `${id}.json`);
fs.writeFileSync(temporary, `${JSON.stringify(request)}\n`, { encoding: "utf8", mode: 0o600 });
fs.renameSync(temporary, requestPath);

const deadline = Date.now() + (timeoutSeconds + 15) * 1000;
while (!fs.existsSync(responsePath) && Date.now() < deadline) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
}
if (!fs.existsSync(responsePath)) {
  console.error("El puente de Windows no devolvio una respuesta a tiempo.");
  process.exit(124);
}
const response = JSON.parse(fs.readFileSync(responsePath, "utf8"));
fs.rmSync(responsePath, { force: true });
if (response.stdout) process.stdout.write(response.stdout);
if (response.stderr) process.stderr.write(response.stderr);
process.exit(Number.isInteger(response.exitCode) ? response.exitCode : 1);
