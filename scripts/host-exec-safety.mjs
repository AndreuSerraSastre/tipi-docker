const COMPOSE_LIFECYCLE = new Set([
  "create",
  "down",
  "kill",
  "restart",
  "rm",
  "run",
  "start",
  "stop",
  "up",
]);

function commandSegments(command) {
  return command.split(/&&|\|\||[;\n]/u).map((part) => part.trim());
}

export function unsafeSelfMutationReason(command) {
  for (const segment of commandSegments(command)) {
    if (!segment) continue;
    const lower = segment.toLowerCase();
    if (
      /^(?:(?:sudo|nohup)\s+)*(?:timeout\s+\S+\s+)?(?:(?:bash|sh)\s+)?(?:\S*\/)?(?:install|stop|update-and-start)\.sh\b/u.test(
        lower,
      )
    ) {
      return "script de ciclo de vida ejecutado dentro del propio gateway";
    }

    const compose = lower.match(
      /\bdocker\b[^|]*?\bcompose\b[^|]*?\b(create|down|kill|restart|rm|run|start|stop|up)\b/u,
    );
    if (compose && COMPOSE_LIFECYCLE.has(compose[1])) {
      const operation = compose[1];
      const hasNoDeps = /(?:^|\s)--no-deps(?:\s|$)/u.test(lower);
      const hasVoice = /\btipi-voice\b/u.test(lower);
      const hasGateway = /\bopenclaw-gateway\b/u.test(lower);
      const hasCli = /\bopenclaw-cli\b/u.test(lower);
      const safeVoiceOperation =
        hasVoice &&
        !hasGateway &&
        !hasCli &&
        operation !== "down" &&
        (!["create", "run", "start", "up"].includes(operation) || hasNoDeps);
      const safeCliRun =
        operation === "run" && hasCli && hasNoDeps && !hasGateway && !hasVoice;
      if (!safeVoiceOperation && !safeCliRun) {
        return "operaci\u00f3n Compose capaz de detener o recrear el propio gateway";
      }
    }

    if (
      /\bdocker\b[^|]*?\b(?:container\s+)?(?:kill|remove|rename|restart|rm|start|stop|update)\b[^|]*?\btipi-openclaw-gateway(?:-1)?\b/u.test(
        lower,
      )
    ) {
      return "operaci\u00f3n Docker directa sobre el propio gateway";
    }
  }
  return "";
}
