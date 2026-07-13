import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const dist = "/app/dist";
const files = readdirSync(dist)
  .filter((name) => name.endsWith(".js"))
  .map((name) => join(dist, name));

const replacements = [
  {
    from: "You are OpenClaw's realtime voice interface. Keep spoken replies concise.",
    to: "Eres la interfaz de voz Realtime de OpenClaw. Habla siempre en español, salvo que la persona te hable claramente en catalán o inglés. Mantén las respuestas habladas concisas.",
  },
  {
    from: 'speak one brief acknowledgement such as "Let me check that for you"',
    to: 'speak only one brief acknowledgement in Spanish, such as "Un momento, lo consulto"',
  },
  {
    from: "Tell the ${audienceLabel} briefly that you are checking, then wait for the final OpenClaw result before answering with the actual result.",
    to: "Di brevemente en español que lo estás comprobando y espera el resultado final de OpenClaw antes de responder.",
  },
  {
    from: "reasoningEffort: trimToUndefined(raw?.reasoningEffort),\n\t\tazureEndpoint:",
    to: "reasoningEffort: trimToUndefined(raw?.reasoningEffort),\n\t\tnoiseReductionType: trimToUndefined(raw?.noiseReductionType),\n\t\ttranscriptionLanguage: trimToUndefined(raw?.transcriptionLanguage),\n\t\ttranscriptionPrompt: trimToUndefined(raw?.transcriptionPrompt),\n\t\tazureEndpoint:",
  },
  {
    from: "noise_reduction: null,\n\t\t\t\t\t\ttranscription: { model: OPENAI_REALTIME_INPUT_TRANSCRIPTION_MODEL },",
    to: "noise_reduction: cfg.noiseReductionType === \"off\" ? null : { type: cfg.noiseReductionType ?? \"far_field\" },\n\t\t\t\t\t\ttranscription: {\n\t\t\t\t\t\t\tmodel: OPENAI_REALTIME_INPUT_TRANSCRIPTION_MODEL,\n\t\t\t\t\t\t\t...cfg.transcriptionLanguage ? { language: cfg.transcriptionLanguage } : {},\n\t\t\t\t\t\t\t...cfg.transcriptionPrompt ? { prompt: cfg.transcriptionPrompt } : {}\n\t\t\t\t\t\t},",
  },
];

const counts = new Array(replacements.length).fill(0);
for (const file of files) {
  let source = readFileSync(file, "utf8");
  let changed = false;
  replacements.forEach(({ from, to }, index) => {
    if (!source.includes(from)) return;
    source = source.replaceAll(from, to);
    counts[index] += 1;
    changed = true;
  });
  if (changed) writeFileSync(file, source);
}

const missing = counts
  .map((count, index) => ({ count, text: replacements[index].from }))
  .filter(({ count }) => count === 0);
if (missing.length) {
  throw new Error(`No se encontraron ${missing.length} plantillas Realtime que debían parchearse`);
}

console.log(`Plantillas Realtime en español aplicadas: ${counts.join(", ")}`);
