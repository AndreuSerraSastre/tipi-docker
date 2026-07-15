import fs from "node:fs";
import path from "node:path";

const templatePath = process.env.TIPI_CONFIG_TEMPLATE ?? "/tipi-config/openclaw.json";
const targetPath = process.env.TIPI_CONFIG_TARGET ?? "/home/node/.openclaw/openclaw.json";

function merge(current, managed) {
  if (Array.isArray(managed)) return managed;
  if (managed && typeof managed === "object") {
    const result = current && typeof current === "object" && !Array.isArray(current) ? { ...current } : {};
    for (const [key, value] of Object.entries(managed)) result[key] = merge(result[key], value);
    return result;
  }
  return managed;
}

const managed = JSON.parse(fs.readFileSync(templatePath, "utf8"));
const agentDefaults = managed?.agents?.defaults;
if (agentDefaults && process.env.TIPI_OPENCLAW_MODEL?.trim()) {
  agentDefaults.model ??= {};
  agentDefaults.model.primary = process.env.TIPI_OPENCLAW_MODEL.trim();
}
if (agentDefaults && process.env.TIPI_OPENCLAW_THINKING?.trim()) {
  const thinking = process.env.TIPI_OPENCLAW_THINKING.trim();
  agentDefaults.thinkingDefault = thinking;
  if (managed?.talk) managed.talk.consultThinkingLevel = thinking;
}
const realtime = managed?.talk?.realtime;
if (realtime && process.env.TIPI_REALTIME_SPEAKER_VOICE?.trim()) {
  realtime.speakerVoice = process.env.TIPI_REALTIME_SPEAKER_VOICE.trim();
}
const openaiRealtime = realtime?.providers?.openai;
if (openaiRealtime) {
  const overrides = {
    noiseReductionType: process.env.TIPI_REALTIME_NOISE_REDUCTION,
    reasoningEffort: process.env.TIPI_REALTIME_REASONING,
    transcriptionLanguage: process.env.TIPI_REALTIME_TRANSCRIPTION_LANGUAGE,
    transcriptionPrompt: process.env.TIPI_REALTIME_TRANSCRIPTION_PROMPT,
  };
  for (const [key, value] of Object.entries(overrides)) {
    if (value?.trim()) openaiRealtime[key] = value.trim();
  }
}
let current = {};
try {
  current = JSON.parse(fs.readFileSync(targetPath, "utf8"));
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

// Versiones anteriores administraban una definición manual de Sol. Luna ya
// forma parte del catálogo nativo de OpenClaw, por lo que esa entrada obsoleta
// solo alteraría metadatos y selección de contexto en instalaciones actualizadas.
const openaiProvider = current?.models?.providers?.openai;
if (Array.isArray(openaiProvider?.models)) {
  openaiProvider.models = openaiProvider.models.filter(
    (model) => model?.id !== "gpt-5.6-sol",
  );
  if (openaiProvider.models.length === 0) delete openaiProvider.models;
  if (Object.keys(openaiProvider).length === 0) delete current.models.providers.openai;
  if (Object.keys(current.models.providers).length === 0) delete current.models.providers;
  if (Object.keys(current.models).length === 0) delete current.models;
}
const updated = `${JSON.stringify(merge(current, managed), null, 2)}\n`;
const previous = fs.existsSync(targetPath) ? fs.readFileSync(targetPath, "utf8") : "";
if (updated !== previous) {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  const temporary = `${targetPath}.tipi.tmp`;
  fs.writeFileSync(temporary, updated, { encoding: "utf8", mode: 0o600 });
  fs.renameSync(temporary, targetPath);
  console.log("Configuración administrada de Tipi actualizada.");
}
