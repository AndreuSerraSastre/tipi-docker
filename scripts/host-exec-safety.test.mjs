import assert from "node:assert/strict";
import test from "node:test";

import { unsafeSelfMutationReason } from "./host-exec-safety.mjs";


const allowed = [
  "docker compose ps",
  "docker compose exec -T openclaw-gateway node --version",
  "docker compose --profile linux-audio stop tipi-voice",
  "docker compose --profile linux-audio up -d --no-deps tipi-voice",
  "docker compose --profile tools run --rm --no-deps openclaw-cli models list",
  "docker restart tipi-tipi-voice-1",
  "systemctl restart --no-block tipi.service",
];

const blocked = [
  "docker compose up -d",
  "docker compose up -d openclaw-gateway",
  "docker compose restart openclaw-gateway",
  "docker compose restart tipi-voice openclaw-gateway",
  "docker compose --env-file /tipi-project/.env -f /tipi-project/compose.yaml up -d --force-recreate tipi-voice",
  "docker compose down",
  "docker compose run --rm openclaw-cli models list",
  "docker restart tipi-openclaw-gateway-1",
  "./scripts/update-and-start.sh",
  "nohup ./scripts/update-and-start.sh",
  "timeout 300 bash /tipi-project/scripts/update-and-start.sh",
  "bash /tipi-project/scripts/stop.sh",
  "sudo sh /tipi-project/scripts/install.sh",
];

for (const command of allowed) {
  test(`permite: ${command}`, () => {
    assert.equal(unsafeSelfMutationReason(command), "");
  });
}

for (const command of blocked) {
  test(`bloquea: ${command}`, () => {
    assert.notEqual(unsafeSelfMutationReason(command), "");
  });
}
